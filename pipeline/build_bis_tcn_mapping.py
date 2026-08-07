import sys, os
import re
import time
import geopandas as gpd
import pandas as pd
from difflib import SequenceMatcher
from sqlalchemy import text

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_engine


def clean_name(name):
    """정류장 명칭 비교용 정제 함수 (특수문자, 괄호, 공백 제거)"""
    if not name or pd.isna(name):
        return ""
    return re.sub(r"[\(\)\[\]\.\s\-_]", "", str(name)).lower()


def compute_text_similarity(s1, s2):
    """두 정류장 명칭 간의 텍스트 유사도 계산 (0.0 ~ 1.0)"""
    c1 = clean_name(s1)
    c2 = clean_name(s2)
    if not c1 or not c2:
        return 0.0
    if c1 == c2:
        return 1.0
    if c1 in c2 or c2 in c1:
        return 0.9
    return SequenceMatcher(None, c1, c2).ratio()


def assign_confidence(row):
    """거리 및 텍스트 유사도 기반 매칭 신뢰도 등급 부여"""
    dist = row["distance_m"]
    sim = row["name_similarity"]

    if dist <= 30 and sim >= 0.9:
        return "EXACT"
    elif dist <= 60 and sim >= 0.7:
        return "HIGH"
    elif dist <= 100 or sim >= 0.8:
        return "MEDIUM"
    else:
        return "LOW"


def build_bis_tcn_mapping():
    engine = get_engine()
    print("==================================================")
    print("BIS - TCN 정류장 정밀 공간/텍스트 매핑 파이프라인 시작")
    print("==================================================")
    t0 = time.time()

    with engine.connect() as conn:
        # 1. BIS 정류장 데이터 로드 (stops_master)
        print("1. BIS 정류장 마스터 데이터 로드 중...")
        bis_gdf = gpd.read_postgis(
            "SELECT stop_id AS bis_stop_id, stop_name AS bis_stop_name, geometry FROM stops_master",
            conn,
            geom_col="geometry",
        )
        print(f"  - BIS 정류장: {len(bis_gdf):,}개")

        # 2. TCN 정류장 데이터 로드 (tcn_sttn_raw)
        print("\n2. TCN 정류장 데이터 로드 중...")
        tcn_sql = """
        SELECT DISTINCT ON (stop_id) 
            stop_id AS tcn_stop_id, 
            stop_name AS tcn_stop_name, 
            stop_ars_no AS tcn_ars_no,
            sigungu_name AS tcn_sigungu,
            dong_name AS tcn_dong,
            CAST(stop_y AS FLOAT) AS lon, 
            CAST(stop_x AS FLOAT) AS lat
        FROM tcn_sttn_raw
        WHERE stop_x IS NOT NULL AND stop_x != '' AND CAST(stop_x AS FLOAT) > 30
        ORDER BY stop_id, op_date DESC;
        """
        tcn_df = pd.read_sql(text(tcn_sql), conn)
        tcn_gdf = gpd.GeoDataFrame(
            tcn_df,
            geometry=gpd.points_from_xy(tcn_df.lon, tcn_df.lat),
            crs="EPSG:4326",
        )
        print(f"  - TCN 정류장: {len(tcn_gdf):,}개")

        # 3. 공간 최근접 매핑 (Spatial Nearest Neighbor within 150m in EPSG:5181)
        print("\n3. 공간 좌표 기준 최근접 정류장 후보 매칭 (EPSG:5181 150m 이내)...")
        bis_metric = bis_gdf.to_crs(epsg=5181)
        tcn_metric = tcn_gdf.to_crs(epsg=5181)

        joined = gpd.sjoin_nearest(
            bis_metric,
            tcn_metric,
            distance_col="distance_m",
            max_distance=150,
            how="inner",
        )

        print(f"  - 매칭 후보 수: {len(joined):,}건")

        # 4. 텍스트 유사도 및 신뢰도 등급 계산
        print("\n4. 텍스트 유사도 계산 및 신뢰도 등급 평가 중...")
        joined["name_similarity"] = joined.apply(
            lambda r: compute_text_similarity(r["bis_stop_name"], r["tcn_stop_name"]),
            axis=1,
        )
        joined["confidence_level"] = joined.apply(assign_confidence, axis=1)

        # 각 BIS 정류장별로 최적의 매칭 1개만 선정 (신뢰도 순 -> 거리순)
        confidence_order = {"EXACT": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
        joined["conf_rank"] = joined["confidence_level"].map(confidence_order)

        # 정렬 후 bis_stop_id별 최고 매칭 선택
        best_matches = (
            joined.sort_values(
                by=["bis_stop_id", "conf_rank", "name_similarity", "distance_m"],
                ascending=[True, False, False, True],
            )
            .groupby("bis_stop_id")
            .first()
            .reset_index()
        )

        # EPSG:4326으로 다시 변환
        result_gdf = gpd.GeoDataFrame(
            best_matches[[
                "bis_stop_id", "bis_stop_name", "tcn_stop_id", "tcn_stop_name",
                "tcn_ars_no", "tcn_sigungu", "tcn_dong", "distance_m",
                "name_similarity", "confidence_level", "geometry"
            ]],
            geometry="geometry",
            crs="EPSG:5181",
        ).to_crs(epsg=4326)

        # 5. PostGIS 테이블 적재 (bis_tcn_stop_mapping)
        print("\n5. PostGIS bis_tcn_stop_mapping 테이블 저장 및 인덱스 생성...")
        result_gdf.to_postgis(
            "bis_tcn_stop_mapping", engine, if_exists="replace", index=False
        )

        index_sqls = [
            "CREATE INDEX IF NOT EXISTS idx_bt_bis_stop_id ON bis_tcn_stop_mapping (bis_stop_id);",
            "CREATE INDEX IF NOT EXISTS idx_bt_tcn_stop_id ON bis_tcn_stop_mapping (tcn_stop_id);",
            "CREATE INDEX IF NOT EXISTS idx_bt_conf ON bis_tcn_stop_mapping (confidence_level);",
            "CREATE INDEX IF NOT EXISTS idx_bt_geom ON bis_tcn_stop_mapping USING GIST (geometry);",
        ]
        for idx in index_sqls:
            conn.execute(text(idx))
        conn.commit()

        # 6. 통계 요약
        stats = result_gdf["confidence_level"].value_counts().to_dict()
        print("\n==================================================")
        print("BIS - TCN 정류장 매핑 파이프라인 완료!")
        print(f"총 매핑 완료 정류장 수: {len(result_gdf):,} / {len(bis_gdf):,}개 ({len(result_gdf)/len(bis_gdf)*100:.1f}%)")
        print("신뢰도 등급 분포:")
        print(f"  - EXACT  (A+: 거리 <=30m & 유사도 >=0.9): {stats.get('EXACT', 0):,}개")
        print(f"  - HIGH   (A : 거리 <=60m & 유사도 >=0.7): {stats.get('HIGH', 0):,}개")
        print(f"  - MEDIUM (B : 거리 <=100m 또는 유사도 >=0.8): {stats.get('MEDIUM', 0):,}개")
        print(f"  - LOW    (C : 기타 근접 매칭): {stats.get('LOW', 0):,}개")
        print(f"소요 시간: {time.time()-t0:.2f}초")
        print("==================================================")


if __name__ == "__main__":
    build_bis_tcn_mapping()
