import geopandas as gpd
import pandas as pd
from rapidfuzz import fuzz
import sys, os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_engine

engine = get_engine()

bis = gpd.read_postgis("SELECT stop_id, stop_name, geometry FROM stops_master", engine, geom_col="geometry")
tcn = gpd.read_postgis("SELECT stop_id, stop_name, geometry FROM tcn_stops_master", engine, geom_col="geometry")

bis = bis.rename(columns={"stop_id": "bis_stop_id", "stop_name": "bis_stop_name"})
tcn = tcn.rename(columns={"stop_id": "tcn_stop_id", "stop_name": "tcn_stop_name"})

# 거리를 미터 단위로 정확히 재려고 투영좌표계로 변환 (중부원점)
bis_m = bis.to_crs(epsg=5181)
tcn_m = tcn.to_crs(epsg=5181)

# 각 BIS 정류장마다 가장 가까운 TCN 정류장 하나씩 찾기 (반경 50m 이내, 없으면 NaN)
matched = gpd.sjoin_nearest(bis_m, tcn_m, how="left", distance_col="distance_m", max_distance=50)

# 이름 유사도 점수 계산 (0~100)
def name_score(row):
    if pd.isna(row["tcn_stop_name"]):
        return None
    return fuzz.ratio(str(row["bis_stop_name"]), str(row["tcn_stop_name"]))

matched["name_score"] = matched.apply(name_score, axis=1)

# 상태 분류
def classify(row):
    if pd.isna(row["tcn_stop_id"]):
        return "unmatched"          # 50m 안에 TCN 정류장이 아예 없음
    elif row["distance_m"] <= 20 and row["name_score"] >= 70:
        return "confirmed"          # 가깝고 이름도 비슷함 -> 신뢰
    else:
        return "review"             # 가깝긴 한데 이름이 다르거나 애매함 -> 사람이 확인 필요

matched["match_status"] = matched.apply(classify, axis=1)

result = matched[[
    "bis_stop_id", "bis_stop_name", "tcn_stop_id", "tcn_stop_name",
    "distance_m", "name_score", "match_status",
]].reset_index(drop=True)

result.to_sql("bis_tcn_stop_mapping", engine, if_exists="replace", index=False)

# 요약 출력
print(result["match_status"].value_counts())
print(f"\n전체 BIS 정류장: {len(result):,}개")

# 검토 필요/실패 목록은 CSV로 따로 뽑아서 눈으로 확인하기 쉽게
result[result["match_status"] != "confirmed"].to_csv(
    "data/processed/bis_tcn_stop_review.csv", index=False, encoding="utf-8-sig"
)
print("검토 필요 목록 -> data/processed/bis_tcn_stop_review.csv 저장")