import pandas as pd
import geopandas as gpd
import sys, os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_engine

engine = get_engine()

# 정류장ID 기준 중복 제거 (날짜별로 반복 저장된 것 중 하나만)
tcn_sttn = pd.read_sql(
    "SELECT DISTINCT ON (stop_id) stop_id, stop_name, stop_x, stop_y "
    "FROM tcn_sttn_raw ORDER BY stop_id, op_date DESC",
    engine,
)

# 주의: 컬럼명은 X/Y지만 실제 값은 위도/경도로 들어있음 (stop_x=위도, stop_y=경도)
tcn_sttn["lat"] = tcn_sttn["stop_x"].astype(float)
tcn_sttn["lon"] = tcn_sttn["stop_y"].astype(float)

geometry = gpd.points_from_xy(tcn_sttn["lon"], tcn_sttn["lat"])
tcn_stops_master = gpd.GeoDataFrame(
    tcn_sttn[["stop_id", "stop_name"]], geometry=geometry, crs="EPSG:4326"
)

tcn_stops_master.to_postgis("tcn_stops_master", engine, if_exists="replace", index=False)
print(f"tcn_stops_master: {len(tcn_stops_master):,}행 (고유 정류장 수)")