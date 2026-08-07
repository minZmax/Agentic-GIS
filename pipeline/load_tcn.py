import pandas as pd
import glob
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_engine
from pipeline.tcn_columns import (
    ROUTE_COLUMNS, STTN_COLUMNS, ROUTESTTN_COLUMNS, DWTCN_COLUMNS,
    CD_TFCMN_COLUMNS, CD_USERTYPE_COLUMNS, CD_CARDGB_COLUMNS, CD_TCBO_COLUMNS,
)

engine = get_engine()
BASE_FOLDER = "data/raw/tcn"
CHUNK_SIZE = 100_000


def find_file(folder, prefix):
    matches = glob.glob(os.path.join(folder, f"{prefix}_*.dat"))
    return matches[0] if matches else None


# ── 0) CD 코드 매핑 파일 적재 (날짜와 무관, 한 번만) ──
CD_FOLDER = os.path.join(BASE_FOLDER, "CD")
cd_files = [
    ("CD_TFCMN", CD_TFCMN_COLUMNS, "cd_transport_mode"),
    ("CD_USERTYPE", CD_USERTYPE_COLUMNS, "cd_user_type"),
    ("CD_CARDGB", CD_CARDGB_COLUMNS, "cd_card_type"),
    ("CD_TCBO", CD_TCBO_COLUMNS, "cd_tcbo"),
]

print("=== 코드 매핑 파일 적재 ===")
for prefix, cols, table in cd_files:
    matches = glob.glob(os.path.join(CD_FOLDER, f"{prefix}*.dat"))
    if not matches:
        print(f"  [{prefix}] 파일 없음, 건너뜀")
        continue
    df = pd.read_csv(matches[0], sep="|", header=None, names=cols, encoding="utf-8", dtype=str)
    df.to_sql(table, engine, if_exists="replace", index=False)  # 코드표는 매번 덮어써도 무방
    print(f"  [{prefix}] {len(df):,}행 적재 완료 -> {table}")


# ── 1) 날짜별 폴더(DATA_YYYYMMDD) 순회 ──
date_folders = sorted([
    d for d in os.listdir(BASE_FOLDER)
    if os.path.isdir(os.path.join(BASE_FOLDER, d)) and d.startswith("DATA_")
])
print(f"\n날짜 폴더 {len(date_folders)}개 발견:", date_folders)

for date_folder in date_folders:
    folder = os.path.join(BASE_FOLDER, date_folder)
    print(f"\n=== {date_folder} 처리 중 ===")

    # route, sttn, routesttn: 크기 작으니 통으로 로드
    for prefix, cols, table in [
        ("ROUTE", ROUTE_COLUMNS, "tcn_route_raw"),
        ("STTN", STTN_COLUMNS, "tcn_sttn_raw"),
        ("ROUTESTTN", ROUTESTTN_COLUMNS, "tcn_routesttn_raw"),
    ]:
        fpath = find_file(folder, prefix)
        if not fpath:
            print(f"  [{prefix}] 파일 없음, 건너뜀")
            continue
        df = pd.read_csv(fpath, sep="|", header=None, names=cols, encoding="utf-8", dtype=str)
        df.to_sql(table, engine, if_exists="append", index=False)
        print(f"  [{prefix}] {len(df):,}행 적재 완료 -> {table}")

    # dwtcn: 대용량이니 청크로 처리
    fpath = find_file(folder, "DWTCN")
    if not fpath:
        print("  [DWTCN] 파일 없음, 건너뜀")
        continue

    total = 0
    for chunk in pd.read_csv(fpath, sep="|", header=None, names=DWTCN_COLUMNS,
                               encoding="utf-8", dtype=str, chunksize=CHUNK_SIZE):
        chunk.to_sql(
            "tcn_dwtcn_raw", engine, if_exists="append", index=False,
            method="multi", chunksize=400,   # 144컬럼 × 400행 ≈ 57,600 파라미터 (제한 이내)
        )
        total += len(chunk)
        print(f"    ...{total:,}행 누적")
    print(f"  [DWTCN] {total:,}행 적재 완료 -> tcn_dwtcn_raw")