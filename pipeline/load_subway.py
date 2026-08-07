import os
from pathlib import Path
from urllib.parse import quote_plus
import pandas as pd
import geopandas as gpd
from sqlalchemy import create_engine

# 1. 경로 설정
BASE_DIR = Path(__file__).resolve().parent.parent
SUBWAY_DIR = BASE_DIR / "data" / "raw" / "subway"

# 2. PostgreSQL DB 접속 정보 
DB_USER = "postgres"
DB_PASS = "1234"      # 실제 비밀번호로 수정
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "goyang"    # DB 이름: goyang

# 비밀번호 URL 인코딩
ENCODED_PASS = quote_plus(DB_PASS)

# GeoPandas to_postgis() 고속 적재(copy_expert)를 지원하는 기본 psycopg2 드라이버 사용
DB_URL = f"postgresql://{DB_USER}:{ENCODED_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DB_URL)

def run():
    # 폴더 안의 모든 .gpkg 파일 검색
    gpkg_files = list(SUBWAY_DIR.glob("*.gpkg"))
    
    if not gpkg_files:
        print(f"❌ .gpkg 파일을 찾을 수 없습니다: {SUBWAY_DIR}")
        return

    print(f"🔍 총 {len(gpkg_files)}개의 GeoPackage(.gpkg) 파일을 발견했습니다:")
    for f in gpkg_files:
        print(f"  - {f.name}")

    # 3. 모든 GPKG 파일 읽기
    gdfs = []
    for gpkg_path in gpkg_files:
        print(f"\n읽는 중: {gpkg_path.name}")
        gdf = gpd.read_file(gpkg_path)
        
        # 좌표계를 WGS84(EPSG:4326, 위경도)로 통일
        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            print("  ↳ 좌표계를 EPSG:4326(WGS84)으로 변환합니다.")
            gdf = gdf.to_crs(epsg=4326)
            
        gdfs.append(gdf)

    # 4. 3개 데이터프레임 병합
    print("\n📦 데이터 병합 중...")
    merged_gdf = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs="EPSG:4326")

    # 5. PostGIS 적재 (goyang DB의 subway_stations 테이블)
    print("🚀 PostGIS 'subway_stations' 테이블에 저장 중...")
    merged_gdf.to_postgis(
        name="subway_stations",
        con=engine,
        if_exists="replace",
        index=False,
    )
    print("✅ 3개 GPKG 파일 병합 및 goyang DB 적재가 완벽히 완료되었습니다!")

if __name__ == "__main__":
    run()