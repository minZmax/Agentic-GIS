"""GeoJSON formatting helpers for map rendering with Graduated Symbol Mapping."""
from __future__ import annotations

import json
import geopandas as gpd
import pandas as pd

from tools.db_tool import (
    search_stops_with_geom,
    get_district_boundary_geom,
    get_district_traffic,
    execute_spatial_query
)


def _ensure_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """평면좌표계(EPSG:5179)인 경우 WGS84 위경도(EPSG:4326)로 안전하게 투영 변환합니다."""
    if gdf is None or gdf.empty:
        return gdf
    try:
        bounds = gdf.total_bounds
        if bounds[0] > 180 or bounds[1] > 90:
            gdf = gdf.set_crs("EPSG:5179", allow_override=True).to_crs("EPSG:4326")
        elif gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        elif gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs("EPSG:4326")
    except Exception as e:
        print(f"⚠️ [map_data] 좌표 변환 경고: {e}")
    return gdf


def _gdf_to_geojson(gdf: gpd.GeoDataFrame) -> dict:
    if gdf is None or gdf.empty:
        return {"type": "FeatureCollection", "features": []}
    gdf = _ensure_wgs84(gdf)
    return json.loads(gdf.to_json())


def _calculate_stop_style(passengers: float, max_passengers: float) -> tuple[str, int]:
    """정류장 이용수요 상대 비율에 따른 마커 색상 및 반지름(px) 반환"""
    if max_passengers <= 0 or passengers <= 0:
        return "#94a3b8", 5  # 이용량 없는 정류장: 회색, 5px
    
    ratio = passengers / max_passengers
    
    # 마커 크기: 6px ~ 16px
    radius = int(6 + (ratio * 10))
    
    # 핫스팟 단계구분 색상
    if ratio >= 0.7:
        color = "#ef4444"  # 빨강 (최고 수요 핫스팟)
    elif ratio >= 0.4:
        color = "#f97316"  # 주황 (고수요)
    elif ratio >= 0.15:
        color = "#eab308"  # 노랑 (보통)
    else:
        color = "#3b82f6"  # 파랑 (저수요)
        
    return color, radius


def get_stops_geojson(df):
    """GeoDataFrame을 null/empty 좌표 없이 안전한 GeoJSON Dict로 변환"""
    if df is None or df.empty or 'geometry' not in df.columns:
        return {"type": "FeatureCollection", "features": []}

    try:
        # 💡 1. geometry가 null이거나 비어있는(is_empty) 행 완전히 제거
        valid_df = df[df['geometry'].notnull()].copy()
        valid_df = valid_df[~valid_df['geometry'].is_empty].copy()

        if valid_df.empty:
            return {"type": "FeatureCollection", "features": []}

        # 💡 2. GeoDataFrame 생성 후 GeoJSON으로 변환
        gdf = gpd.GeoDataFrame(valid_df, geometry='geometry', crs="EPSG:4326")
        return json.loads(gdf.to_json())
    except Exception as e:
        print(f"⚠️ [get_stops_geojson 오류]: {e}")
        return {"type": "FeatureCollection", "features": []}


def get_district_geojson(district_name: str) -> dict:
    """택지지구 경계(Polygon)와 지구 내 정류장 이용수요 단계구분(Point) 결합 GeoJSON"""
    features = []

    # 1. 택지지구 경계 폴리곤 추가
    try:
        boundary_gdf = get_district_boundary_geom(district_name)
        if not boundary_gdf.empty:
            boundary_gdf = _ensure_wgs84(boundary_gdf)
            for _, row in boundary_gdf.iterrows():
                if row.geometry is not None:
                    feat = json.loads(gpd.GeoSeries([row.geometry]).to_json())["features"][0]
                    feat["properties"] = {
                        "layer_type": "boundary",
                        "name": row.get("admin_name", district_name)
                    }
                    features.append(feat)
    except Exception as e:
        print(f"⚠️ [map_data] 경계 데이터 조회 생략 ({district_name}): {e}")

    # 2. 지구 내 정류장 + 이용수요 단계구분 시각화
    try:
        traffic_df = get_district_traffic(district_name)
        if not traffic_df.empty:
            max_passengers = traffic_df["total_passengers"].max() if "total_passengers" in traffic_df.columns else 0

            if isinstance(traffic_df, gpd.GeoDataFrame) and "geometry" in traffic_df.columns:
                stops_gdf = _ensure_wgs84(traffic_df)
            else:
                stop_ids = [str(sid) for sid in traffic_df["stop_id"].dropna().unique()]
                geom_gdf = search_stops_with_geom(stop_ids=stop_ids)
                if not geom_gdf.empty:
                    merged = pd.merge(traffic_df, geom_gdf[["stop_id", "geometry"]], on="stop_id", how="inner")
                    stops_gdf = _ensure_wgs84(gpd.GeoDataFrame(merged, geometry="geometry", crs="EPSG:4326"))
                else:
                    stops_gdf = gpd.GeoDataFrame()

            if not stops_gdf.empty:
                for _, row in stops_gdf.iterrows():
                    if row.geometry is not None:
                        feat = json.loads(gpd.GeoSeries([row.geometry]).to_json())["features"][0]
                        passengers = float(row.get("total_passengers", 0) or 0)
                        color, radius = _calculate_stop_style(passengers, max_passengers)
                        
                        feat["properties"] = {
                            "layer_type": "bus_stop",
                            "stop_id": row.get("stop_id"),
                            "stop_name": row.get("stop_name"),
                            "dong_name": row.get("dong_name"),
                            "total_passengers": passengers,
                            "total_boardings": float(row.get("total_boardings", 0) or 0),
                            "total_alightings": float(row.get("total_alightings", 0) or 0),
                            "marker_color": color,
                            "marker_radius": radius
                        }
                        features.append(feat)
    except Exception as e:
        print(f"⚠️ [map_data] 정류장 시각화 에러 ({district_name}): {e}")

    return {"type": "FeatureCollection", "features": features}


def get_housing_district_summary_geojson() -> dict:
    """고양시 모든 택지지구 경계(Polygon)에 이용량 데이터(단계구분도)를 결합하여 GeoJSON 반환 (안전 모드)"""
    try:
        import json
        import traceback
        import geopandas as gpd
        from tools.db_tool import get_housing_district_summary, execute_spatial_query
        
        # 1. 택지지구별 이용량 통계 조회
        summary_df = get_housing_district_summary()
        
        # 판다스 병합(Merge) 시 지오메트리 유실 버그를 막기 위해 순수 Python Dictionary 로 매핑
        stats_dict = {}
        max_pass = 0
        if summary_df is not None and not summary_df.empty:
            for _, row in summary_df.iterrows():
                raw_name = str(row.get("housing_district_name", ""))
                clean = raw_name.replace("지구", "").replace("신도시", "").replace("지역", "").strip()
                passengers = float(row.get("total_passengers", 0) or 0)
                stops = int(row.get("total_stops", 0) or 0)
                stats_dict[clean] = {"passengers": passengers, "stops": stops, "raw_name": raw_name}
                if passengers > max_pass:
                    max_pass = passengers

        # 2. 공간 경계 데이터 조회 (컬럼이 없을 경우를 대비한 2중 안전 쿼리)
        try:
            gdf = execute_spatial_query("SELECT admin_name, geometry FROM admin_boundary WHERE admin_level = 'housing_district'")
        except Exception as sql_err:
            print(f"⚠️ [map_data] 필터링 실패, 전체 경계 조회로 폴백: {sql_err}")
            gdf = execute_spatial_query("SELECT admin_name, geometry FROM admin_boundary")
            
        if gdf.empty:
            print("❌ [map_data] admin_boundary 테이블에서 지도를 가져오지 못했습니다.")
            return {"type": "FeatureCollection", "features": []}
        
        gdf = _ensure_wgs84(gdf)
        features = []
        
        # 3. 데이터 매핑 및 시각화 속성 부여
        for _, row in gdf.iterrows():
            if row.geometry is None:
                continue
                
            admin_name = str(row.get("admin_name", ""))
            clean_name = admin_name.replace("지구", "").replace("신도시", "").replace("지역", "").strip()
            
            # 통계 데이터가 있으면 가져오고 없으면 0
            stat = stats_dict.get(clean_name, {"passengers": 0, "stops": 0, "raw_name": admin_name})
            passengers = stat["passengers"]
            
            ratio = (passengers / max_pass) if max_pass > 0 else 0
            if ratio >= 0.5:        fill_color, fill_opacity = "#6b21a8", 0.65
            elif ratio >= 0.15:     fill_color, fill_opacity = "#9333ea", 0.45
            elif ratio >= 0.03:     fill_color, fill_opacity = "#c084fc", 0.35
            else:                   fill_color, fill_opacity = "#e9d5ff", 0.20

            feat = json.loads(gpd.GeoSeries([row.geometry]).to_json())["features"][0]
            feat["properties"] = {
                "layer_type": "boundary",
                "admin_name": stat["raw_name"] or admin_name,
                "total_passengers": passengers,
                "total_stops": stat["stops"],
                "fillColor": fill_color,
                "fillOpacity": fill_opacity
            }
            features.append(feat)
            
        return {"type": "FeatureCollection", "features": features}
    
    except Exception as e:
        import traceback
        print(f"❌ [map_data] 단계구분도 생성 중 치명적 에러 발생:")
        traceback.print_exc()
        return {"type": "FeatureCollection", "features": []}

def get_od_flow_geojson(df: pd.DataFrame) -> dict:
    """OD 통행 데이터를 수요 기반 동적 굵기 및 화살표 시각화용 GeoJSON으로 변환"""
    if df is None or df.empty:
        return {"type": "FeatureCollection", "features": []}

    features = []
    
    # 1. 통행량/승객수 컬럼 확인 및 최대값 계산
    val_col = "total_passengers" if "total_passengers" in df.columns else ("total_trips" if "total_trips" in df.columns else None)
    max_val = df[val_col].max() if (val_col and not df.empty) else 1
    max_val = max(float(max_val or 1), 1.0)

    if isinstance(df, gpd.GeoDataFrame) and "geometry" in df.columns:
        gdf = _ensure_wgs84(df)
        for _, row in gdf.iterrows():
            if row.geometry is None:
                continue
            
            feat = json.loads(gpd.GeoSeries([row.geometry]).to_json())["features"][0]
            val = float(row.get(val_col, 0) or 0) if val_col else 0
            ratio = val / max_val
            
            # 동적 굵기(2px ~ 12px) 및 투명도(0.4 ~ 0.9) 설정
            line_weight = int(2 + (ratio * 10))
            line_opacity = round(0.4 + (ratio * 0.5), 2)
            
            feat["properties"] = {
                "layer_type": "od_line",
                "start_dong": row.get("start_dong") or row.get("start_stop_name"),
                "end_dong": row.get("end_dong") or row.get("end_stop_name"),
                "total_passengers": val,
                "total_trips": row.get("total_trips", 0),
                "avg_distance_km": row.get("avg_distance_km", 0),
                "avg_time_min": row.get("avg_time_min", 0),
                "line_weight": line_weight,
                "line_opacity": line_opacity,
                "line_color": "#ff3b30" if ratio > 0.5 else ("#ff6b6b" if ratio > 0.2 else "#ffa8a8")
            }
            features.append(feat)

        return {"type": "FeatureCollection", "features": features}

    return {"type": "FeatureCollection", "features": []}

def get_default_layers():
    """앱 초기 로딩 시 지도에 표시할 기본 레이어 (고양시 행정구역 경계) 데이터 반환"""
    sql = """
        SELECT admin_name, admin_level, geometry 
        FROM admin_boundary
    """
    try:
        gdf = execute_spatial_query(sql)
        if not gdf.empty:
            # GeoDataFrame을 GeoJSON Dict 구조로 변환하여 반환
            return gdf.__geo_interface__
    except Exception as e:
        print(f"⚠️ [map_data] 기본 레이어(admin_boundary) 로드 실패: {e}")
        
    # 예외 발생 또는 데이터가 없을 경우 빈 GeoJSON 구조 반환
    return {"type": "FeatureCollection", "features": []}