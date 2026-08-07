import folium
import geopandas as gpd
import pandas as pd
import sys, os

from sqlalchemy import text
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.db_tool import get_district_boundary_geom, search_stops_with_geom, engine


def create_stops_map(stops_df: pd.DataFrame, output_html: str = "stops_map.html", title: str = "정류장 이용객 시각화") -> str:
    """정류장별 승하차량을 서클 마커 크기 및 색상으로 지도 시각화"""
    if stops_df.empty:
        return None

    stop_ids = stops_df["stop_id"].dropna().astype(str).unique().tolist()
    geom_gdf = search_stops_with_geom(stop_ids=stop_ids)

    merged = pd.merge(stops_df, geom_gdf[["stop_id", "geometry"]], on="stop_id", how="inner")
    
    # 만약 stop_admin_mapping과 ID 매핑이 안 되면 tcn_sttn_raw에서 lat/lon 수집
    if merged.empty:
        ids_str = "', '".join(stop_ids)
        sttn_sql = f"SELECT DISTINCT ON (stop_id) stop_id, CAST(stop_x AS FLOAT) as lat, CAST(stop_y AS FLOAT) as lon FROM tcn_sttn_raw WHERE stop_id IN ('{ids_str}');"
        sttn_coords = pd.read_sql(text(sttn_sql), engine)
        if not sttn_coords.empty:
            merged = pd.merge(stops_df, sttn_coords, on="stop_id", how="inner")
            if not merged.empty:
                geometry = gpd.points_from_xy(merged.lon, merged.lat)
                merged_gdf = gpd.GeoDataFrame(merged, geometry=geometry, crs="EPSG:4326")
            else:
                return None
        else:
            return None
    else:
        merged_gdf = gpd.GeoDataFrame(merged, geometry="geometry", crs="EPSG:4326")

    center = [merged_gdf.geometry.y.mean(), merged_gdf.geometry.x.mean()]
    m = folium.Map(location=center, zoom_start=13, tiles="cartodbpositron")

    # 헤더 타이틀 추가
    title_html = f'<h4 align="center" style="font-size:16px"><b>{title}</b></h4>'
    m.get_root().html.add_child(folium.Element(title_html))

    max_passengers = merged_gdf["total_passengers"].max() if "total_passengers" in merged_gdf.columns and merged_gdf["total_passengers"].max() > 0 else 1

    for _, row in merged_gdf.iterrows():
        lat = row.geometry.y
        lon = row.geometry.x
        stop_name = row.get("stop_name", "정류장")
        passengers = row.get("total_passengers", 0)
        boardings = row.get("total_boardings", 0)
        alightings = row.get("total_alightings", 0)
        dong = row.get("dong_name", "-")

        radius = 5 + (passengers / max_passengers) * 20

        color = "red" if passengers > (max_passengers * 0.5) else "orange" if passengers > (max_passengers * 0.2) else "blue"

        tooltip_text = f"<b>{stop_name}</b> ({dong})<br>총 이용객: {passengers:,}명 (승차: {boardings:,} / 하차: {alightings:,})"

        folium.CircleMarker(
            location=[lat, lon],
            radius=radius,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.6,
            tooltip=tooltip_text,
        ).add_to(m)

    output_path = os.path.abspath(output_html)
    m.save(output_path)
    return output_path


def create_district_map(district_name: str, output_html: str = "district_map.html") -> str:
    """택지지구 경계 및 내부 정류장을 지도상에 표시"""
    bound_gdf = get_district_boundary_geom(district_name=district_name)
    stops_gdf = search_stops_with_geom(district_name=district_name)

    if bound_gdf.empty and stops_gdf.empty:
        return None

    if not bound_gdf.empty:
        bounds = bound_gdf.total_bounds  # [minx, miny, maxx, maxy]
        center = [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2]
    else:
        center = [stops_gdf.geometry.y.mean(), stops_gdf.geometry.x.mean()]

    m = folium.Map(location=center, zoom_start=14, tiles="cartodbpositron")

    # 택지지구 폴리곤
    if not bound_gdf.empty:
        for _, row in bound_gdf.iterrows():
            folium.GeoJson(
                row.geometry,
                style_function=lambda x: {"color": "purple", "weight": 3, "fillColor": "purple", "fillOpacity": 0.15},
                tooltip=f"택지지구: {row['admin_name']}",
            ).add_to(m)

    # 정류장 마커
    if not stops_gdf.empty:
        for _, row in stops_gdf.iterrows():
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=6,
                color="darkblue",
                fill=True,
                fill_color="blue",
                fill_opacity=0.7,
                tooltip=f"<b>{row['stop_name']}</b> ({row['housing_district_name']})",
            ).add_to(m)

    title_html = f'<h4 align="center" style="font-size:16px"><b>{district_name} 공간 및 버스 정류장 시각화</b></h4>'
    m.get_root().html.add_child(folium.Element(title_html))

    output_path = os.path.abspath(output_html)
    m.save(output_path)
    return output_path


def create_od_flow_map(od_df: pd.DataFrame, output_html: str = "od_flow_map.html") -> str:
    """행정동 간 이동 흐름(OD)을 중심점 연결선으로 지도 시각화"""
    if od_df.empty:
        return None

    # 행정동 중심점 좌표 구하기
    dong_sql = "SELECT admin_name, ST_AsText(ST_Centroid(geometry)) as centroid FROM admin_boundary WHERE admin_level = 'dong';"
    dong_df = pd.read_sql(text(dong_sql), engine)

    # Centroid WKT 파싱
    coords = {}
    for _, r in dong_df.iterrows():
        try:
            wkt = r["centroid"]  # POINT(x y)
            x_y = wkt.replace("POINT(", "").replace(")", "").split()
            coords[r["admin_name"]] = (float(x_y[1]), float(x_y[0]))
        except Exception:
            continue

    m = folium.Map(location=[37.658, 126.832], zoom_start=12, tiles="cartodbpositron")

    title_html = '<h4 align="center" style="font-size:16px"><b>행정동 간 버스 통행 흐름(OD) 시각화</b></h4>'
    m.get_root().html.add_child(folium.Element(title_html))

    lines_added = 0
    for _, row in od_df.iterrows():
        start = row.get("start_dong")
        end = row.get("end_dong")
        trips = row.get("total_trips", 0)

        if start in coords and end in coords:
            start_coord = coords[start]
            end_coord = coords[end]

            # 출발/도착 마커
            folium.CircleMarker(location=start_coord, radius=5, color="green", fill=True, tooltip=f"출발: {start}").add_to(m)
            folium.CircleMarker(location=end_coord, radius=5, color="red", fill=True, tooltip=f"도착: {end}").add_to(m)

            # 연결선
            popup_txt = f"{start} ➡️ {end}<br>통행건수: {trips:,}건<br>평균거리: {row.get('avg_distance_km', 0)}km<br>평균시간: {row.get('avg_time_min', 0)}분"
            folium.PolyLine(
                locations=[start_coord, end_coord],
                color="blue",
                weight=2 + min(trips / 1000, 8),
                opacity=0.6,
                tooltip=popup_txt,
            ).add_to(m)
            lines_added += 1

    output_path = os.path.abspath(output_html)
    m.save(output_path)
    return output_path
