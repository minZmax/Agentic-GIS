import geopandas as gpd
import glob
import os

def load_all_geojson(folder_path: str) -> gpd.GeoDataFrame:
    """폴더 안의 geojson 파일들을 모두 읽어서 하나로 합침"""
    files = glob.glob(os.path.join(folder_path, "*.geojson"))
    print(f"{folder_path} 에서 {len(files)}개 파일 발견")

    gdf_list = []
    for f in files:
        gdf = gpd.read_file(f)
        gdf["source_file"] = os.path.basename(f)  # 어느 파일에서 왔는지 기록 (나중에 디버깅용)
        gdf_list.append(gdf)

    if not gdf_list:
        raise FileNotFoundError(f"{folder_path}에 geojson 파일이 없습니다")

    combined = gpd.GeoDataFrame(
        __import__("pandas").concat(gdf_list, ignore_index=True),
        crs=gdf_list[0].crs
    )
    return combined

routes = load_all_geojson("data/raw/routes")
print("\n=== 노선 데이터 (합친 결과) ===")
print("전체 행 개수:", len(routes))
print("컬럼:", routes.columns.tolist())
print("좌표계(CRS):", routes.crs)
print(routes.head())

stops = load_all_geojson("data/raw/stops")
print("\n=== 정류장 데이터 ===")
print("전체 행 개수:", len(stops))
print("컬럼:", stops.columns.tolist())
print("좌표계(CRS):", stops.crs)
print(stops.head())