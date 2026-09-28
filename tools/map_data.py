"""GeoJSON formatting helpers for map rendering with Graduated Symbol Mapping."""
from __future__ import annotations

import json
import math
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

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


def _calculate_half_arrow_coords(slon: float, slat: float, elon: float, elat: float) -> list[tuple[float, float]]:
    """
    기점(A) -> 종점(B) -> 반화살표 깃(C) -> 종점(B) 4점 순환 구조.
    화살표 머리의 위경도 크기를 0.001~0.003도(약 100m~300m) 범위로 정밀 제한하여,
    장거리(서울) 및 단거리(고양 내부) 노선 모두 화면 픽셀 두께와 자연스러운 비율의 반화살표(⇀)를 생성합니다.
    """
    # 위도 37.6도 기준 경도/위도 비율 보정 (111km / 88km ≈ 1.261)
    LAT_FACTOR = 1.261

    dx = elon - slon
    dy = elat - slat

    vx = dx
    vy = dy * LAT_FACTOR
    length = math.sqrt(vx * vx + vy * vy)

    if length == 0:
        return [(slon, slat), (elon, elat), (elon, elat), (elon, elat)]

    # [핵심 보정]: 화살표 머리 크기(도 단위)를 0.001 ~ 0.003도로 절대 제한 (상한 300m)
    # 장거리 노선에서도 화살표 머리가 거대해지지 않고 픽셀 두께(3~8px)와 어울리는 크기 유지
    head_len = min(0.003, max(0.001, length * 0.03))

    # 진행 방향 각도 및 반화살표(⇀) 오른쪽 깃 꺾임각 (155도)
    angle = math.atan2(vy, vx)
    wing_angle = angle - math.radians(155)

    wx = head_len * math.cos(wing_angle)
    wy = head_len * math.sin(wing_angle)

    wing_lon = elon + wx
    wing_lat = elat + (wy / LAT_FACTOR)

    # A -> B -> C -> B (4점 순환 LineString)
    return [(slon, slat), (elon, elat), (wing_lon, wing_lat), (elon, elat)]


def get_od_flow_geojson(df: pd.DataFrame) -> dict:
    """OD 통행 데이터를 반화살표(⇀) 시각화용 GeoJSON으로 변환"""
    if df is None or df.empty:
        return {"type": "FeatureCollection", "features": []}

    gdf = df.copy()

    # 1. 기종점 좌표 파싱 및 LineString 생성
    geoms = []
    has_direct_coords = all(col in gdf.columns for col in ["start_lon", "start_lat", "end_lon", "end_lat"])

    if has_direct_coords:
        for _, row in gdf.iterrows():
            try:
                slon, slat = float(row["start_lon"]), float(row["start_lat"])
                elon, elat = float(row["end_lon"]), float(row["end_lat"])
                if slon > 0 and slat > 0 and elon > 0 and elat > 0:
                    coords = _calculate_half_arrow_coords(slon, slat, elon, elat)
                    geoms.append(LineString(coords))
                else:
                    geoms.append(None)
            except Exception:
                geoms.append(None)
    else:
        coords_map = _get_dong_centroid_map()
        for _, row in gdf.iterrows():
            s_dong = str(row.get("start_dong", "")).strip()
            e_dong = str(row.get("end_dong", "")).strip()

            s_coord = coords_map.get(s_dong)
            e_coord = coords_map.get(e_dong)

            if not s_coord and len(s_dong) > 2 and s_dong[-2] in "1234":
                s_coord = coords_map.get(s_dong[:-2] + "동")
            if not e_coord and len(e_dong) > 2 and e_dong[-2] in "1234":
                e_coord = coords_map.get(e_dong[:-2] + "동")

            if s_coord and e_coord:
                coords = _calculate_half_arrow_coords(s_coord[0], s_coord[1], e_coord[0], e_coord[1])
                geoms.append(LineString(coords))
            else:
                geoms.append(None)

    gdf["geometry"] = geoms
    gdf = gdf.dropna(subset=["geometry"]).copy()

    if gdf.empty:
        return {"type": "FeatureCollection", "features": []}

    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs="EPSG:4326")

    # 2. 통행량 기반 동적 스타일 부여
    val_col = "total_passengers" if "total_passengers" in gdf.columns else ("total_trips" if "total_trips" in gdf.columns else None)
    max_val = gdf[val_col].max() if (val_col and not gdf.empty) else 1
    max_val = max(float(max_val or 1), 1.0)

    gdf = _ensure_wgs84(gdf)
    features = []

    for _, row in gdf.iterrows():
        if row.geometry is None:
            continue

        feat = json.loads(gpd.GeoSeries([row.geometry]).to_json())["features"][0]
        val = float(row.get(val_col, 0) or 0) if val_col else 0
        ratio = val / max_val

        line_weight = int(2 + (ratio * 8))
        line_opacity = round(0.5 + (ratio * 0.4), 2)

        feat["properties"] = {
            "layer_type": "od_line",
            "start_stop_name": row.get("start_stop_name"),
            "end_stop_name": row.get("end_stop_name"),
            "start_dong": row.get("start_dong") or row.get("start_district"),
            "end_dong": row.get("end_dong"),
            "total_passengers": val,
            "total_trips": row.get("total_trips", 0),
            "avg_distance_km": row.get("avg_distance_km", 0),
            "avg_time_min": row.get("avg_time_min", 0),
            "line_weight": line_weight,
            "line_opacity": line_opacity,
            "line_color": "#ff3b30" if ratio > 0.5 else ("#ff6b6b" if ratio > 0.2 else "#ffa8a8"),
            "fill": False,
            "fillOpacity": 0
        }
        features.append(feat)

    return {"type": "FeatureCollection", "features": features}


def _get_dong_centroid_map() -> dict[str, tuple[float, float]]:
    """DB의 admin_boundary 및 stop_admin_mapping에서 행정동 중심점 좌표(lon, lat) 조회 및 매핑"""
    from tools.db_tool import execute_query
    sql = """
        WITH dong_centers AS (
            SELECT 
                CASE 
                    WHEN admin_name LIKE '%1동' OR admin_name LIKE '%2동' OR admin_name LIKE '%3동' OR admin_name LIKE '%4동' 
                    THEN SUBSTRING(admin_name FROM 1 FOR LENGTH(admin_name)-2) || '동'
                    ELSE admin_name
                END AS clean_dong,
                ST_X(ST_Centroid(geometry)) AS lon,
                ST_Y(ST_Centroid(geometry)) AS lat
            FROM admin_boundary
            WHERE geometry IS NOT NULL
            UNION ALL
            SELECT 
                dong_name AS clean_dong,
                AVG(ST_X(geometry)) AS lon,
                AVG(ST_Y(geometry)) AS lat
            FROM stop_admin_mapping
            WHERE geometry IS NOT NULL AND dong_name IS NOT NULL
            GROUP BY dong_name
        )
        SELECT clean_dong, AVG(lon) AS lon, AVG(lat) AS lat
        FROM dong_centers
        GROUP BY clean_dong
    """
    try:
        df = execute_query(sql)
        coords = {}
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                dong = str(row.get("clean_dong", "")).strip()
                lon = float(row.get("lon", 0) or 0)
                lat = float(row.get("lat", 0) or 0)
                if dong and lon > 0 and lat > 0:
                    coords[dong] = (lon, lat)
        return coords
    except Exception as e:
        print(f"⚠️ [map_data] 행정동 중심점 조회 실패: {e}")
        return {}


def _calculate_stop_style(passengers: float, max_passengers: float) -> tuple[str, int]:
    """정류장 이용수요 상대 비율에 따른 마커 색상 및 반지름(px) 반환"""
    if max_passengers <= 0 or passengers <= 0:
        return "#94a3b8", 5
    ratio = passengers / max_passengers
    radius = int(6 + (ratio * 10))
    if ratio >= 0.7:
        color = "#ef4444"
    elif ratio >= 0.4:
        color = "#f97316"
    elif ratio >= 0.15:
        color = "#eab308"
    else:
        color = "#3b82f6"
    return color, radius


def get_stops_geojson(df):
    """GeoDataFrame을 null/empty 좌표 없이 안전한 GeoJSON Dict로 변환"""
    if df is None or df.empty or 'geometry' not in df.columns:
        return {"type": "FeatureCollection", "features": []}

    try:
        valid_df = df[df['geometry'].notnull()].copy()
        valid_df = valid_df[~valid_df['geometry'].is_empty].copy()
        if valid_df.empty:
            return {"type": "FeatureCollection", "features": []}
        gdf = gpd.GeoDataFrame(valid_df, geometry='geometry', crs="EPSG:4326")
        return json.loads(gdf.to_json())
    except Exception as e:
        print(f"⚠️ [get_stops_geojson 오류]: {e}")
        return {"type": "FeatureCollection", "features": []}


def get_district_geojson(district_name: str) -> dict:
    """택지지구 경계(Polygon)와 지구 내 정류장 이용수요 단계구분(Point) 결합 GeoJSON"""
    features = []
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
    """고양시 모든 택지지구 경계(Polygon)에 이용량 데이터(단계구분도)를 결합하여 GeoJSON 반환"""
    try:
        from tools.db_tool import get_housing_district_summary, execute_spatial_query
        summary_df = get_housing_district_summary()
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

        try:
            gdf = execute_spatial_query("SELECT admin_name, geometry FROM admin_boundary WHERE admin_level = 'housing_district'")
        except Exception:
            gdf = execute_spatial_query("SELECT admin_name, geometry FROM admin_boundary")

        if gdf.empty:
            return {"type": "FeatureCollection", "features": []}

        gdf = _ensure_wgs84(gdf)
        features = []

        for _, row in gdf.iterrows():
            if row.geometry is None:
                continue
            admin_name = str(row.get("admin_name", ""))
            clean_name = admin_name.replace("지구", "").replace("신도시", "").replace("지역", "").strip()
            stat = stats_dict.get(clean_name, {"passengers": 0, "stops": 0, "raw_name": admin_name})
            passengers = stat["passengers"]

            ratio = (passengers / max_pass) if max_pass > 0 else 0
            if ratio >= 0.5:
                fill_color, fill_opacity = "#6b21a8", 0.65
            elif ratio >= 0.15:
                fill_color, fill_opacity = "#9333ea", 0.45
            elif ratio >= 0.03:
                fill_color, fill_opacity = "#c084fc", 0.35
            else:
                fill_color, fill_opacity = "#e9d5ff", 0.20

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
        print(f"❌ [map_data] 단계구분도 생성 중 에러: {e}")
        return {"type": "FeatureCollection", "features": []}


def get_default_layers():
    """앱 초기 로딩 시 지도에 표시할 기본 레이어 반환"""
    sql = "SELECT admin_name, admin_level, geometry FROM admin_boundary"
    try:
        gdf = execute_spatial_query(sql)
        if not gdf.empty:
            return gdf.__geo_interface__
    except Exception as e:
        print(f"⚠️ [map_data] 기본 레이어 로드 실패: {e}")
    return {"type": "FeatureCollection", "features": []}

def get_district_od_combined_geojson(district_name: str, od_df: pd.DataFrame) -> dict:
    """
    택지지구 경계(Polygon) + 지구 내 정류장(Point) + OD 화살표선(LineString)
    3가지 요소를 결합한 오버레이 GeoJSON 반환
    """
    combined_features = []

    # 1. 택지지구 경계 폴리곤 추가
    try:
        boundary_gdf = get_district_boundary_geom(district_name)
        if boundary_gdf is not None and not boundary_gdf.empty:
            boundary_gdf = _ensure_wgs84(boundary_gdf)
            for _, row in boundary_gdf.iterrows():
                if row.geometry is not None:
                    feat = json.loads(gpd.GeoSeries([row.geometry]).to_json())["features"][0]
                    feat["properties"] = {
                        "layer_type": "od_boundary",
                        "name": row.get("admin_name", district_name)
                    }
                    combined_features.append(feat)
    except Exception as e:
        print(f"⚠️ [map_data] 택지지구 경계 오버레이 실패: {e}")

    # 2. 지구 내 버스 정류장 원형 마커 추가
    try:
        stops_gdf = search_stops_with_geom(district_name=district_name)
        if stops_gdf is not None and not stops_gdf.empty:
            stops_gdf = _ensure_wgs84(stops_gdf)
            for _, row in stops_gdf.iterrows():
                if row.geometry is not None:
                    feat = json.loads(gpd.GeoSeries([row.geometry]).to_json())["features"][0]
                    feat["properties"] = {
                        "layer_type": "od_stop",
                        "stop_id": row.get("stop_id"),
                        "stop_name": row.get("stop_name"),
                        "housing_district_name": row.get("housing_district_name")
                    }
                    combined_features.append(feat)
    except Exception as e:
        print(f"⚠️ [map_data] 정류장 오버레이 실패: {e}")

    # 3. OD 화살표선 추가
    try:
        od_geojson = get_od_flow_geojson(od_df)
        if od_geojson and "features" in od_geojson:
            combined_features.extend(od_geojson["features"])
    except Exception as e:
        print(f"⚠️ [map_data] OD 화살표선 결합 실패: {e}")

    return {"type": "FeatureCollection", "features": combined_features}