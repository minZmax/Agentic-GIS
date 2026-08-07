import geopandas as gpd
import pandas as pd
import re
from sqlalchemy import text
import sys, os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_engine

engine = get_engine()
stops = gpd.read_postgis("SELECT * FROM bis_stops", engine, geom_col="geometry")

# 1) source_file에서 노선ID 추출: "011번 정류장정보(241308701).geojson" -> "241308701"
def extract_route_id(filename: str) -> str:
    match = re.search(r"\((\d+)\)", filename)
    return match.group(1) if match else None

stops["route_id"] = stops["source_file"].apply(extract_route_id)

missing = stops["route_id"].isna().sum()
print(f"route_id 추출 실패한 행: {missing}개")
if missing > 0:
    print("샘플:", stops[stops["route_id"].isna()]["source_file"].head().tolist())

# 2) 노선-정류장 순서 테이블 (중복 허용 — 같은 정류장이 여러 노선에 등장 가능)
route_stop_sequence = stops[["route_id", "stop_id", "seq", "direction"]].copy()
route_stop_sequence.to_sql("route_stop_sequence", engine, if_exists="replace", index=False)
print(f"route_stop_sequence: {len(route_stop_sequence):,}행 적재")

# 3) 정류장 마스터 테이블 (stop_id 기준 중복 제거)
stops_master = stops.drop_duplicates(subset="stop_id", keep="first")
stops_master = stops_master[["stop_id", "stop_name", "geometry"]].reset_index(drop=True)
stops_master.to_postgis("stops_master", engine, if_exists="replace", index=False)
print(f"stops_master: {len(stops_master):,}행 (고유 정류장 수)")

# 4) 공간 인덱스 추가 — 검색/조인 속도를 위해 지오메트리 컬럼마다 GIST 인덱스 생성
with engine.connect() as conn:
    for table, geom_col in [
        ("bis_routes", "geometry"),
        ("stops_master", "geometry"),
        ("admin_boundary", "geometry"),
    ]:
        idx_name = f"idx_{table}_geom"
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} USING GIST ({geom_col});"))
    conn.commit()
print("공간 인덱스 생성 완료")