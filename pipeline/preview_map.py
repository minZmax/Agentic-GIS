import geopandas as gpd
import folium
import sys, os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_engine

engine = get_engine()

routes = gpd.read_postgis("SELECT * FROM bis_routes", engine, geom_col="geometry")
stops = gpd.read_postgis("SELECT * FROM bis_stops", engine, geom_col="geometry")
boundary = gpd.read_postgis("SELECT * FROM admin_boundary", engine, geom_col="geometry")

center = [stops.geometry.y.mean(), stops.geometry.x.mean()]
m = folium.Map(location=center, zoom_start=12, tiles="cartodbpositron")

# 1) 행정경계 - 레벨별로 색 다르게, 레이어 나눠서 켜고 끌 수 있게
level_colors = {"si": "black", "gu": "blue", "dong": "green", "housing_district": "purple"}
for level, color in level_colors.items():
    layer = folium.FeatureGroup(name=f"행정경계 ({level})")
    subset = boundary[boundary["admin_level"] == level]
    for _, row in subset.iterrows():
        folium.GeoJson(
            row.geometry,
            style_function=lambda x, c=color: {"color": c, "weight": 2, "fillOpacity": 0.05},
            tooltip=row["admin_name"],
        ).add_to(layer)
    layer.add_to(m)

# 2) 노선 (샘플 20개)
route_layer = folium.FeatureGroup(name="노선 (샘플)")
for _, row in routes.head(20).iterrows():
    folium.GeoJson(
        row.geometry,
        style_function=lambda x: {"color": "red", "weight": 3},
        tooltip=row.get("route_name", ""),
    ).add_to(route_layer)
route_layer.add_to(m)

# 3) 정류장 (샘플 200개)
stop_layer = folium.FeatureGroup(name="정류장 (샘플)")
for _, row in stops.head(200).iterrows():
    folium.CircleMarker(
        location=[row.geometry.y, row.geometry.x],
        radius=2, color="orange", fill=True,
        tooltip=row.get("정류장명", ""),
    ).add_to(stop_layer)
stop_layer.add_to(m)

folium.LayerControl(collapsed=False).add_to(m)  # 우측 상단에서 레이어 켜고 끌 수 있음

m.save("preview_map.html")
print("preview_map.html 생성 완료")