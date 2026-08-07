import geopandas as gpd
import pandas as pd
import shapely
import sys, os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_engine

engine = get_engine()

# level: (폴더, 원본 이름컬럼, 원본 코드컬럼)
levels = {
    "si":   {"folder": "data/raw/boundary/si",   "name_col": "SIGUNGU_NM", "code_col": "SIGUNGU_CD"},
    "gu":   {"folder": "data/raw/boundary/gu",   "name_col": "SIGUNGU_NM", "code_col": "SIGUNGU_CD"},
    "dong": {"folder": "data/raw/boundary/dong", "name_col": "ADM_NM",     "code_col": "ADM_CD"},
    "housing_district": {"folder": "data/raw/boundary/housing_district"},
}

for level_name, info in levels.items():
    folder = info["folder"]
    if not os.path.exists(folder):
        print(f"[{level_name}] 폴더 없음, 건너뜀")
        continue

    shp_files = [f for f in os.listdir(folder) if f.endswith(".shp")]
    if not shp_files:
        print(f"[{level_name}] shp 파일 없음, 건너뜀")
        continue

    if level_name == "housing_district":
        # 택지지구는 여러 개의 shp 파일이 존재하므로 파일명(지구명)을 admin_name으로 읽어서 하나로 합침
        gdf_list = []
        for shp in shp_files:
            file_path = os.path.join(folder, shp)
            district_name = os.path.splitext(shp)[0]
            g = gpd.read_file(file_path).to_crs(epsg=4326)
            g["admin_name"] = district_name
            g["admin_code"] = None
            g["base_date"] = None
            g["admin_level"] = level_name
            g = g[["admin_name", "admin_code", "base_date", "admin_level", "geometry"]]
            gdf_list.append(g)
        gdf = gpd.GeoDataFrame(pd.concat(gdf_list, ignore_index=True), crs="EPSG:4326")
        print(f"\n=== {level_name} ({len(shp_files)}개 shp 파일) === 전체 행 개수: {len(gdf)}")
    else:
        file_path = os.path.join(folder, shp_files[0])
        gdf = gpd.read_file(file_path)
        print(f"\n=== {level_name} ({file_path}) === 행 개수: {len(gdf)}")

        gdf = gdf.to_crs(epsg=4326)

        # 공통 스키마로 컬럼명 통일
        gdf = gdf.rename(columns={
            info["name_col"]: "admin_name",
            info["code_col"]: "admin_code",
            "BASE_DATE": "base_date",
        })
        gdf["admin_level"] = level_name
        gdf = gdf[["admin_name", "admin_code", "base_date", "admin_level", "geometry"]]

    # Z 차원(3D 고도 데이터)이 포함된 경우 2D로 강제 변환
    gdf["geometry"] = shapely.force_2d(gdf.geometry)

    gdf.to_postgis(
        "admin_boundary",
        engine,
        if_exists="replace" if level_name == "si" else "append",
        index=False,
    )

print("\n전체 적재 완료")
