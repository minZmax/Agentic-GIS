import sys, os
from sqlalchemy import text

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_engine


def build_stop_admin_mapping():
    engine = get_engine()
    print("=== 정류장 ↔ 행정동 & 택지지구 공간 매핑 테이블 생성 중 ===")

    create_table_sql = """
    DROP TABLE IF EXISTS stop_admin_mapping;

    CREATE TABLE stop_admin_mapping AS
    SELECT 
        s.stop_id,
        s.stop_name,
        g.admin_name AS gu_name,
        d.admin_name AS dong_name,
        d.admin_code AS dong_code,
        h.admin_name AS housing_district_name,
        s.geometry
    FROM stops_master s
    LEFT JOIN admin_boundary g 
        ON g.admin_level = 'gu' AND ST_Within(s.geometry, g.geometry)
    LEFT JOIN admin_boundary d 
        ON d.admin_level = 'dong' AND ST_Within(s.geometry, d.geometry)
    LEFT JOIN admin_boundary h 
        ON h.admin_level = 'housing_district' AND ST_Within(s.geometry, h.geometry);
    """

    index_sqls = [
        "CREATE INDEX IF NOT EXISTS idx_stop_admin_stop_id ON stop_admin_mapping (stop_id);",
        "CREATE INDEX IF NOT EXISTS idx_stop_admin_dong_name ON stop_admin_mapping (dong_name);",
        "CREATE INDEX IF NOT EXISTS idx_stop_admin_housing_name ON stop_admin_mapping (housing_district_name);",
        "CREATE INDEX IF NOT EXISTS idx_stop_admin_geom ON stop_admin_mapping USING GIST (geometry);",
    ]

    with engine.connect() as conn:
        conn.execute(text(create_table_sql))
        print("stop_admin_mapping 공간 매핑 완료!")

        for idx_sql in index_sqls:
            conn.execute(text(idx_sql))
        conn.commit()
        print("인덱스 생성 완료!")

        # 요약 통계 출력
        res = conn.execute(text("""
            SELECT 
                COUNT(*) as total_stops,
                COUNT(dong_name) as mapped_dong,
                COUNT(housing_district_name) as mapped_housing
            FROM stop_admin_mapping;
        """)).mappings().fetchone()
        
        print(
            f"\n[매핑 통계]\n"
            f"- 전체 고유 정류장: {res['total_stops']:,}개\n"
            f"- 행정동 매핑 성공: {res['mapped_dong']:,}개\n"
            f"- 택지지구 내 정류장: {res['mapped_housing']:,}개\n"
        )


if __name__ == "__main__":
    build_stop_admin_mapping()
