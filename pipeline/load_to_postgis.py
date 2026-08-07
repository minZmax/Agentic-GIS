import geopandas as gpd
import glob
import os
import pandas as pd
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_engine


def load_all_geojson(folder_path: str) -> gpd.GeoDataFrame:
    files = glob.glob(os.path.join(folder_path, "*.geojson"))
    gdf_list = []
    for f in files:
        gdf = gpd.read_file(f)
        gdf["source_file"] = os.path.basename(f)
        gdf_list.append(gdf)
    combined = gpd.GeoDataFrame(pd.concat(gdf_list, ignore_index=True), crs=gdf_list[0].crs)
    return combined


# 1. 불러오기
routes = load_all_geojson("data/raw/routes")
stops = load_all_geojson("data/raw/stops")

# 2. 좌표계 변환: EPSG:5181 -> EPSG:4326 (위경도 표준)
routes = routes.to_crs(epsg=4326)
stops = stops.to_crs(epsg=4326)

# 3. 컬럼 정리 (한글 컬럼명 -> DB에서 쓰기 편한 영문명)
routes = routes.drop(columns=["length(km)"])
routes = routes.rename(columns={
    "노선ID": "route_id", "노선명": "route_name", "운수사명": "operator",
    "노선구분": "route_type", "방향": "direction",
    "기점": "start_point", "종점": "end_point",
    "평일배차간격(분)": "weekday_interval_min", "평일첫차시각": "weekday_first", "평일막차시각": "weekday_last",
    "토요일배차간격(분)": "sat_interval_min", "토요일첫차시각": "sat_first", "토요일막차시각": "sat_last",
    "일요일배차간격(분)": "sun_interval_min", "일요일첫차시각": "sun_first", "일요일막차시각": "sun_last",
    "공휴일배차간격(분)": "holiday_interval_min", "공휴일첫차시각": "holiday_first", "공휴일막차시각": "holiday_last",
})

stops = stops.drop(columns=["X", "Y"])
stops = stops.rename(columns={
    "정류장ID": "stop_id", "정류장명": "stop_name", "순번": "seq", "방향": "direction",
})

# 4. PostGIS에 테이블로 적재
engine = get_engine()
routes.to_postgis("bis_routes", engine, if_exists="replace", index=False)
stops.to_postgis("bis_stops", engine, if_exists="replace", index=False)

print("적재 완료!")
print("routes:", len(routes), "행 ->", routes.columns.tolist())
print("stops:", len(stops), "행 ->", stops.columns.tolist())