import sys, os
import time
from sqlalchemy import text

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_engine


def build_tcn_index_and_summary():
    engine = get_engine()
    print("==================================================")
    print("TCN 대용량 데이터(395만 건) 인덱싱 & 요약 뷰 생성 시작")
    print("==================================================")

    # 1. B-Tree 인덱스 생성
    indexes = [
        ("idx_tcn_dwtcn_op_date", "tcn_dwtcn_raw", "op_date"),
        ("idx_tcn_dwtcn_user_type", "tcn_dwtcn_raw", "user_type_cd"),
        ("idx_tcn_dwtcn_start_stop", "tcn_dwtcn_raw", "start_stop_id"),
        ("idx_tcn_dwtcn_end_stop", "tcn_dwtcn_raw", "end_stop_id"),
        ("idx_tcn_dwtcn_board_stop1", "tcn_dwtcn_raw", "board_stop_id_1"),
        ("idx_tcn_dwtcn_alight_stop1", "tcn_dwtcn_raw", "alight_stop_id_1"),
        ("idx_tcn_sttn_stop_id", "tcn_sttn_raw", "stop_id"),
        ("idx_tcn_sttn_dong", "tcn_sttn_raw", "dong_name"),
        ("idx_tcn_route_route_id", "tcn_route_raw", "route_id"),
    ]

    with engine.connect() as conn:
        print("\n1. B-Tree 인덱스 생성 중...")
        for idx_name, table, col in indexes:
            t0 = time.time()
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({col});"))
            conn.commit()
            print(f"  - {idx_name} ({table}.{col}) 인덱스 완료 ({time.time()-t0:.2f}초)")

        # 2. 일별 정류장별 승하차 요약 테이블 (summary_daily_stop_traffic)
        print("\n2. 일별 정류장별 승하차 요약 테이블(summary_daily_stop_traffic) 생성 중...")
        t0 = time.time()
        conn.execute(text("DROP TABLE IF EXISTS summary_daily_stop_traffic;"))
        create_daily_stop_sql = """
        CREATE TABLE summary_daily_stop_traffic AS
        WITH boardings AS (
            SELECT op_date, start_stop_id AS stop_id, COUNT(*) AS board_count, SUM(CAST(total_passenger_count AS INTEGER)) AS board_passengers
            FROM tcn_dwtcn_raw
            WHERE start_stop_id IS NOT NULL AND start_stop_id != ''
            GROUP BY op_date, start_stop_id
        ),
        alightings AS (
            SELECT op_date, end_stop_id AS stop_id, COUNT(*) AS alight_count, SUM(CAST(total_passenger_count AS INTEGER)) AS alight_passengers
            FROM tcn_dwtcn_raw
            WHERE end_stop_id IS NOT NULL AND end_stop_id != ''
            GROUP BY op_date, end_stop_id
        ),
        sttn_unique AS (
            SELECT DISTINCT ON (stop_id) stop_id, stop_name, sigungu_name, dong_name
            FROM tcn_sttn_raw
            ORDER BY stop_id, op_date DESC
        )
        SELECT 
            COALESCE(b.op_date, a.op_date) AS op_date,
            COALESCE(b.stop_id, a.stop_id) AS stop_id,
            s.stop_name,
            s.sigungu_name,
            s.dong_name,
            COALESCE(b.board_count, 0) AS total_boardings,
            COALESCE(a.alight_count, 0) AS total_alightings,
            (COALESCE(b.board_passengers, 0) + COALESCE(a.alight_passengers, 0)) AS total_passengers
        FROM boardings b
        FULL OUTER JOIN alightings a ON b.op_date = a.op_date AND b.stop_id = a.stop_id
        LEFT JOIN sttn_unique s ON COALESCE(b.stop_id, a.stop_id) = s.stop_id;
        """
        conn.execute(text(create_daily_stop_sql))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sum_stop_op_date ON summary_daily_stop_traffic (op_date);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sum_stop_id ON summary_daily_stop_traffic (stop_id);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sum_stop_dong ON summary_daily_stop_traffic (dong_name);"))
        conn.commit()
        print(f"  - summary_daily_stop_traffic 생성 완료 ({time.time()-t0:.2f}초)")

        # 3. 행정동 간 OD(Origin-Destination) 이동량 요약 테이블 (summary_dong_od_flow)
        print("\n3. 행정동 간 OD 통행 요약 테이블(summary_dong_od_flow) 생성 중...")
        t0 = time.time()
        conn.execute(text("DROP TABLE IF EXISTS summary_dong_od_flow;"))
        create_od_sql = """
        CREATE TABLE summary_dong_od_flow AS
        WITH sttn_map AS (
            SELECT DISTINCT ON (stop_id) stop_id, sigungu_name, dong_name
            FROM tcn_sttn_raw
            ORDER BY stop_id, op_date DESC
        )
        SELECT 
            d.op_date,
            s1.sigungu_name AS start_sigungu,
            s1.dong_name AS start_dong,
            s2.sigungu_name AS end_sigungu,
            s2.dong_name AS end_dong,
            COUNT(*) AS trip_count,
            SUM(CAST(d.total_passenger_count AS INTEGER)) AS total_passenger_count,
            ROUND(AVG(CAST(d.total_distance AS NUMERIC)) / 1000.0, 2) AS avg_trip_distance_km,
            ROUND(AVG(CAST(d.total_trip_time AS NUMERIC)) / 60.0, 2) AS avg_trip_time_min
        FROM tcn_dwtcn_raw d
        LEFT JOIN sttn_map s1 ON d.start_stop_id = s1.stop_id
        LEFT JOIN sttn_map s2 ON d.end_stop_id = s2.stop_id
        WHERE d.start_stop_id IS NOT NULL AND d.end_stop_id IS NOT NULL
        GROUP BY d.op_date, s1.sigungu_name, s1.dong_name, s2.sigungu_name, s2.dong_name;
        """
        conn.execute(text(create_od_sql))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_od_op_date ON summary_dong_od_flow (op_date);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_od_start_dong ON summary_dong_od_flow (start_dong);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_od_end_dong ON summary_dong_od_flow (end_dong);"))
        conn.commit()
        print(f"  - summary_dong_od_flow 생성 완료 ({time.time()-t0:.2f}초)")

        # 요약 결과 출력
        r1 = conn.execute(text("SELECT COUNT(*) FROM summary_daily_stop_traffic;")).scalar()
        r2 = conn.execute(text("SELECT COUNT(*) FROM summary_dong_od_flow;")).scalar()

        print("\n==================================================")
        print("TCN 데이터 인덱싱 & 요약 뷰 생성 완료!")
        print(f"- summary_daily_stop_traffic: {r1:,}행 레코드")
        print(f"- summary_dong_od_flow: {r2:,}행 OD 통행 레코드")
        print("==================================================")


if __name__ == "__main__":
    build_tcn_index_and_summary()
