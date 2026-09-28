"""Read-only, parameterized data access for the GIS agent."""
from __future__ import annotations
import re
import pandas as pd
import geopandas as gpd
from sqlalchemy import text, bindparam
from shapely.wkt import loads as wkt_loads
from shapely import wkb
from shapely.geometry import Point

from db.connection import get_engine

engine = get_engine()
TRUSTED_MAPPING = "b.confidence_level IN ('EXACT', 'HIGH', 'MEDIUM')"


def database_is_available() -> tuple[bool, str]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "PostgreSQL 연결됨"
    except Exception as exc:
        return False, f"DB 연결 실패: {type(exc).__name__}"


def execute_query(sql: str, params: dict | None = None) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def execute_spatial_query(sql: str, params: dict = None) -> gpd.GeoDataFrame:
    """PostGIS DB 공간 데이터 파싱 및 위경도(Lat/Lng) 좌표 순서 자동 교정"""
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(sql), conn, params=params or {})

        if df.empty or 'geometry' not in df.columns:
            return gpd.GeoDataFrame()

        def parse_and_fix_geometry(val):
            if val is None or pd.isna(val):
                return None
            
            geom = None
            if isinstance(val, (bytes, memoryview)):
                try: geom = wkb.loads(bytes(val))
                except Exception: pass
            elif isinstance(val, str):
                try: geom = wkt_loads(val)
                except Exception: pass

            if geom is None or geom.is_empty:
                return None

            # 💡 [핵심] X, Y 좌표 범위를 체크하여 Point(경도 126.x, 위도 37.x) 표준 순서로 맞춤
            if geom.geom_type == 'Point':
                x, y = geom.x, geom.y
                if 30.0 <= x <= 45.0 and 120.0 <= y <= 135.0:
                    return Point(y, x)
                elif 120.0 <= x <= 135.0 and 30.0 <= y <= 45.0:
                    return Point(x, y)
            return geom

        df['geometry'] = df['geometry'].apply(parse_and_fix_geometry)
        df = df[df['geometry'].notnull()].copy()

        if df.empty:
            return gpd.GeoDataFrame()

        gdf = gpd.GeoDataFrame(df, geometry='geometry')

        # TM 좌표계(X, Y > 1000)인 경우 WGS84(4326) 변환
        sample_geom = gdf.geometry.iloc[0]
        if sample_geom and hasattr(sample_geom, 'x') and (sample_geom.x > 1000 or sample_geom.y > 1000):
            gdf.crs = "EPSG:5179"
            gdf = gdf.to_crs(epsg=4326)
        else:
            gdf.crs = "EPSG:4326"

        return gdf
    except Exception as e:
        print(f"⚠️ [execute_spatial_query 오류]: {e}")
        return gpd.GeoDataFrame()


# ---------------------------------------------------------------------------
# 💡 Text-to-SQL 지원: LLM(Gemini)이 직접 작성한 SELECT 쿼리를 안전하게 실행
# ---------------------------------------------------------------------------

class UnsafeSQLError(ValueError):
    """검증을 통과하지 못한 SQL(SELECT 이외의 구문 등)에 대해 발생시키는 예외."""


# SELECT/WITH 조회문에서는 등장할 이유가 없는, 데이터 변경/스키마 변경/서버 제어 키워드
_FORBIDDEN_SQL_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE",
    "GRANT", "REVOKE", "CREATE", "EXEC", "EXECUTE", "COPY",
    "MERGE", "CALL", "VACUUM", "REINDEX", "COMMENT", "LOCK",
    "SET", "RESET", "DO",
)


def _validate_readonly_sql(sql: str) -> str:
    """SELECT(또는 WITH ... SELECT) 조회문인지, 위험 키워드가 없는지 검사."""
    if not sql or not sql.strip():
        raise UnsafeSQLError("빈 SQL은 실행할 수 없습니다.")

    cleaned = sql.strip().rstrip(";").strip()

    # 세미콜론으로 여러 SQL문을 이어 붙이는 것 방지 (SQL 인젝션의 대표적 패턴)
    if ";" in cleaned:
        raise UnsafeSQLError("한 번에 하나의 SELECT 문만 실행할 수 있습니다 (세미콜론으로 여러 문장을 연결할 수 없습니다).")

    upper = cleaned.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        raise UnsafeSQLError("SELECT(또는 WITH ... SELECT) 조회문만 실행할 수 있습니다.")

    for keyword in _FORBIDDEN_SQL_KEYWORDS:
        if re.search(rf"\b{keyword}\b", upper):
            raise UnsafeSQLError(f"허용되지 않은 키워드가 포함되어 있습니다: {keyword}")

    return cleaned


def execute_readonly_sql(sql: str, row_limit: int = 200) -> pd.DataFrame:
    """LLM이 생성한 SQL을 검증 후 읽기 전용 트랜잭션으로 실행.

    이중 안전장치:
      1) 애플리케이션 레벨: SELECT/WITH 여부 및 금지 키워드 검사 (_validate_readonly_sql)
      2) DB 레벨: 트랜잭션을 'READ ONLY'로 시작 -> 검증을 통과한 SQL이라도
         실제로 데이터를 변경하려 하면 PostgreSQL이 자체적으로 거부함
    """
    cleaned = _validate_readonly_sql(sql)

    if "LIMIT" not in cleaned.upper():
        cleaned = f"SELECT * FROM ({cleaned}) AS _subquery LIMIT {row_limit}"

    with engine.begin() as conn:
        conn.execute(text("SET LOCAL statement_timeout = '10000'"))  # 10초 넘으면 강제 중단
        conn.execute(text("SET TRANSACTION READ ONLY"))
        return pd.read_sql(text(cleaned), conn)


def _clean_district_name(name: str) -> str:
    if not name:
        return ""
    return name.replace("지구", "").replace("지역", "").replace("신도시", "").strip()


def get_top_stops(limit: int = 10) -> pd.DataFrame:
    """고양시 관내 이용량 상위 버스 정류장 조회 (CTE 서브쿼리로 속도 최적화)"""
    sql = f"""
        WITH top_traffic AS (
            -- 1. 이용량 상위 정류장 ID를 인덱스로 초고속 우선 추출
            SELECT 
                b.bis_stop_id AS stop_id,
                SUM(s.total_passengers) AS total_passengers
            FROM summary_daily_stop_traffic s
            JOIN bis_tcn_stop_mapping b ON s.stop_id = b.tcn_stop_id AND {TRUSTED_MAPPING}
            GROUP BY b.bis_stop_id
            ORDER BY total_passengers DESC
            LIMIT :fetch_limit
        )
        -- 2. 상위 정류장(최대 30건)에 대해서만 공간 좌표 변환 및 매핑 수행
        SELECT 
            m.stop_id, 
            m.stop_name, 
            m.dong_name, 
            m.housing_district_name, 
            ST_AsText(
                CASE 
                    WHEN ST_X(ST_Centroid(m.geometry)) > 1000 
                    THEN ST_Transform(ST_SetSRID(m.geometry, 5179), 4326)
                    ELSE ST_SetSRID(m.geometry, 4326)
                END
            ) AS geometry,
            t.total_passengers
        FROM top_traffic t
        JOIN stop_admin_mapping m ON t.stop_id = m.stop_id
        WHERE m.geometry IS NOT NULL
        ORDER BY t.total_passengers DESC
        LIMIT :limit
    """
    # 여유 있게 3배수를 먼저 뽑은 후 매핑된 결과 중 상위 limit개 반환
    df = execute_spatial_query(sql, {"limit": limit, "fetch_limit": limit * 3})
    if not df.empty:
        df["is_subway"] = False
    return df


def get_district_traffic(district_name: str) -> gpd.GeoDataFrame:
    clean_name = _clean_district_name(district_name)
    sql = f"""
        SELECT m.housing_district_name, m.stop_id, m.stop_name, m.dong_name,
               ST_AsText(
                   CASE 
                       WHEN ST_X(ST_Centroid(m.geometry)) > 1000 
                       THEN ST_Transform(ST_SetSRID(m.geometry, 5179), 4326)
                       ELSE ST_SetSRID(m.geometry, 4326)
                   END
               ) AS geometry,
               COALESCE(SUM(s.total_boardings), 0) AS total_boardings,
               COALESCE(SUM(s.total_alightings), 0) AS total_alightings,
               COALESCE(SUM(s.total_passengers), 0) AS total_passengers
        FROM stop_admin_mapping m
        LEFT JOIN bis_tcn_stop_mapping b ON m.stop_id = b.bis_stop_id AND {TRUSTED_MAPPING}
        LEFT JOIN summary_daily_stop_traffic s ON b.tcn_stop_id = s.stop_id
        WHERE m.housing_district_name ILIKE :district
        GROUP BY m.housing_district_name, m.stop_id, m.stop_name, m.dong_name, m.geometry
        ORDER BY total_passengers DESC
    """
    return execute_spatial_query(sql, {"district": f"%{clean_name}%"})


def get_housing_district_summary() -> pd.DataFrame:
    return execute_query(f"""
        SELECT m.housing_district_name, COUNT(DISTINCT m.stop_id) AS total_stops,
               COALESCE(SUM(s.total_boardings), 0) AS total_boardings,
               COALESCE(SUM(s.total_alightings), 0) AS total_alightings,
               COALESCE(SUM(s.total_passengers), 0) AS total_passengers
        FROM stop_admin_mapping m
        LEFT JOIN bis_tcn_stop_mapping b ON m.stop_id = b.bis_stop_id AND {TRUSTED_MAPPING}
        LEFT JOIN summary_daily_stop_traffic s ON b.tcn_stop_id = s.stop_id
        WHERE m.housing_district_name IS NOT NULL
        GROUP BY m.housing_district_name ORDER BY total_passengers DESC
    """)


def get_dong_od_flow(start_dong: str | None = None, end_dong: str | None = None, limit: int = 10) -> pd.DataFrame:
    conditions, params = ["start_dong IS NOT NULL", "end_dong IS NOT NULL"], {"limit": max(1, min(int(limit), 100))}
    if start_dong:
        conditions.append("start_dong ILIKE :start_dong")
        params["start_dong"] = f"%{start_dong}%"
    if end_dong:
        conditions.append("end_dong ILIKE :end_dong")
        params["end_dong"] = f"%{end_dong}%"
    return execute_query(f"""
        SELECT start_sigungu, start_dong, end_sigungu, end_dong,
               SUM(trip_count) AS total_trips, SUM(total_passenger_count) AS total_passengers,
               ROUND(AVG(avg_trip_distance_km), 2) AS avg_distance_km,
               ROUND(AVG(avg_trip_time_min), 2) AS avg_time_min
        FROM summary_dong_od_flow WHERE {' AND '.join(conditions)}
        GROUP BY start_sigungu, start_dong, end_sigungu, end_dong
        ORDER BY total_trips DESC LIMIT :limit
    """, params)


def get_stop_od_flow(
    start_district: str | None = None,
    start_dong: str | None = None,
    end_is_subway: bool = False,
    end_station_name: str | None = None,
    limit: int = 15
) -> pd.DataFrame:
    """정류장 ↔ 지하철역 / 개별 정류장 간 OD 수송 패턴 및 좌표 조회"""
    conditions = ["s1.geometry IS NOT NULL", "s2.geometry IS NOT NULL"]
    params = {"limit": max(1, min(int(limit), 100))}

    if start_district:
        conditions.append("(s1.housing_district_name ILIKE :start_district OR s1.dong_name ILIKE :start_district)")
        params["start_district"] = f"%{start_district}%"
    elif start_dong:
        conditions.append("s1.dong_name ILIKE :start_dong")
        params["start_dong"] = f"%{start_dong}%"

    if end_is_subway or end_station_name:
        if end_station_name:
            conditions.append("(m2.bis_stop_name ILIKE :end_station OR s2.stop_name ILIKE :end_station)")
            params["end_station"] = f"%{end_station_name}%"
        else:
            conditions.append("(m2.bis_stop_name ILIKE '%역%' OR s2.stop_name ILIKE '%역%')")

    sql = f"""
        SELECT 
            m1.bis_stop_name AS start_stop_name,
            s1.dong_name AS start_dong,
            s1.housing_district_name AS start_district,
            ST_X(
                CASE WHEN ST_X(ST_Centroid(s1.geometry)) > 1000 
                     THEN ST_Transform(ST_SetSRID(s1.geometry, 5179), 4326) 
                     ELSE ST_SetSRID(s1.geometry, 4326) END
            ) AS start_lon,
            ST_Y(
                CASE WHEN ST_X(ST_Centroid(s1.geometry)) > 1000 
                     THEN ST_Transform(ST_SetSRID(s1.geometry, 5179), 4326) 
                     ELSE ST_SetSRID(s1.geometry, 4326) END
            ) AS start_lat,
            m2.bis_stop_name AS end_stop_name,
            s2.dong_name AS end_dong,
            ST_X(
                CASE WHEN ST_X(ST_Centroid(s2.geometry)) > 1000 
                     THEN ST_Transform(ST_SetSRID(s2.geometry, 5179), 4326) 
                     ELSE ST_SetSRID(s2.geometry, 4326) END
            ) AS end_lon,
            ST_Y(
                CASE WHEN ST_X(ST_Centroid(s2.geometry)) > 1000 
                     THEN ST_Transform(ST_SetSRID(s2.geometry, 5179), 4326) 
                     ELSE ST_SetSRID(s2.geometry, 4326) END
            ) AS end_lat,
            COUNT(*) AS total_trips,
            SUM(CAST(d.total_passenger_count AS INTEGER)) AS total_passengers
        FROM tcn_dwtcn_raw d
        JOIN bis_tcn_stop_mapping m1 ON d.start_stop_id = m1.tcn_stop_id AND m1.confidence_level IN ('EXACT', 'HIGH', 'MEDIUM')
        JOIN stop_admin_mapping s1 ON m1.bis_stop_id = s1.stop_id
        JOIN bis_tcn_stop_mapping m2 ON d.end_stop_id = m2.tcn_stop_id AND m2.confidence_level IN ('EXACT', 'HIGH', 'MEDIUM')
        JOIN stop_admin_mapping s2 ON m2.bis_stop_id = s2.stop_id
        WHERE {' AND '.join(conditions)}
        GROUP BY m1.bis_stop_name, s1.dong_name, s1.housing_district_name, s1.geometry,
                 m2.bis_stop_name, s2.dong_name, s2.geometry
        ORDER BY total_trips DESC
        LIMIT :limit
    """
    try:
        return execute_query(sql, params)
    except Exception as e:
        print(f"⚠️ [get_stop_od_flow 오류]: {e}")
        return pd.DataFrame()


def get_all_subway_traffic(limit: int = 100) -> pd.DataFrame:
    """고양시 관내(admin_boundary) 경계 내 순수 지하철역 수송 수요 조회"""
    sql = f"""
        WITH raw_subway AS (
            SELECT 
                s.stop_id,
                s.stop_name,
                s.dong_name,
                COALESCE(m.geometry, (
                    SELECT m2.geometry 
                    FROM stop_admin_mapping m2 
                    WHERE m2.stop_name ILIKE concat('%', s.stop_name, '%') 
                      AND m2.geometry IS NOT NULL 
                    LIMIT 1
                )) AS raw_geom,
                SUM(s.total_passengers) AS total_passengers,
                SUM(s.total_boardings) AS total_boardings,
                SUM(s.total_alightings) AS total_alightings
            FROM summary_daily_stop_traffic s
            LEFT JOIN stop_admin_mapping m ON s.stop_id = m.stop_id
            WHERE (
                LENGTH(s.stop_id) <= 5 
                OR s.stop_id IN (
                    SELECT DISTINCT tcn_stop_id 
                    FROM bis_tcn_stop_mapping 
                    WHERE tcn_stop_name ILIKE '%역%'
                )
            )
            GROUP BY s.stop_id, s.stop_name, s.dong_name, m.geometry
        )
        SELECT 
            r.stop_id,
            r.stop_name,
            r.dong_name,
            ST_AsText(
                CASE 
                    WHEN ST_X(ST_Centroid(r.raw_geom)) > 1000 
                    THEN ST_Transform(ST_SetSRID(r.raw_geom, 5179), 4326)
                    ELSE ST_SetSRID(r.raw_geom, 4326)
                END
            ) AS geometry,
            COALESCE(r.total_passengers, 0) AS total_passengers,
            COALESCE(r.total_boardings, 0) AS total_boardings,
            COALESCE(r.total_alightings, 0) AS total_alightings
        FROM raw_subway r
        WHERE r.raw_geom IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM admin_boundary ab
              WHERE ST_Intersects(
                  CASE WHEN ST_X(ST_Centroid(r.raw_geom)) > 1000 THEN ST_Transform(ST_SetSRID(r.raw_geom, 5179), 4326) ELSE ST_SetSRID(r.raw_geom, 4326) END,
                  CASE WHEN ST_X(ST_Centroid(ab.geometry)) > 1000 THEN ST_Transform(ST_SetSRID(ab.geometry, 5179), 4326) ELSE ST_SetSRID(ab.geometry, 4326) END
              )
          )
        ORDER BY total_passengers DESC
        LIMIT :limit
    """
    try:
        df = execute_spatial_query(sql, {"limit": limit})
        if not df.empty:
            df["is_subway"] = True
            return df
    except Exception as e:
        print(f"⚠️ [db_tool] 전체 지하철역 조회 오류: {e}")

    return pd.DataFrame()


def get_subway_traffic_by_name(station_name: str) -> pd.DataFrame:
    clean_name = (
        station_name.replace("지하철", "")
        .replace("3호선", "")
        .replace("경의중앙선", "")
        .replace("경의선", "")
        .replace("전철", "")
        .replace("gtx", "")
        .replace("역", "")
        .strip()
    )
    
    sql = f"""
        WITH raw_subway AS (
            SELECT 
                s.stop_id,
                s.stop_name,
                s.dong_name,
                COALESCE(m.geometry, (
                    SELECT m2.geometry 
                    FROM stop_admin_mapping m2 
                    WHERE m2.stop_name ILIKE concat('%', s.stop_name, '%') 
                      AND m2.geometry IS NOT NULL 
                    LIMIT 1
                )) AS raw_geom,
                SUM(s.total_passengers) AS total_passengers,
                SUM(s.total_boardings) AS total_boardings,
                SUM(s.total_alightings) AS total_alightings
            FROM summary_daily_stop_traffic s
            LEFT JOIN stop_admin_mapping m ON s.stop_id = m.stop_id
            WHERE s.stop_name ILIKE :search_name
              AND (
                  LENGTH(s.stop_id) <= 5 
                  OR s.stop_id IN (
                      SELECT DISTINCT tcn_stop_id 
                      FROM bis_tcn_stop_mapping 
                      WHERE tcn_stop_name ILIKE '%역%'
                  )
              )
            GROUP BY s.stop_id, s.stop_name, s.dong_name, m.geometry
        )
        SELECT 
            r.stop_id,
            r.stop_name,
            r.dong_name,
            ST_AsText(
                CASE 
                    WHEN ST_X(ST_Centroid(r.raw_geom)) > 1000 
                    THEN ST_Transform(ST_SetSRID(r.raw_geom, 5179), 4326)
                    ELSE ST_SetSRID(r.raw_geom, 4326)
                END
            ) AS geometry,
            COALESCE(r.total_passengers, 0) AS total_passengers,
            COALESCE(r.total_boardings, 0) AS total_boardings,
            COALESCE(r.total_alightings, 0) AS total_alightings
        FROM raw_subway r
        WHERE r.raw_geom IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM admin_boundary ab
              WHERE ST_Intersects(
                  CASE WHEN ST_X(ST_Centroid(r.raw_geom)) > 1000 THEN ST_Transform(ST_SetSRID(r.raw_geom, 5179), 4326) ELSE ST_SetSRID(r.raw_geom, 4326) END,
                  CASE WHEN ST_X(ST_Centroid(ab.geometry)) > 1000 THEN ST_Transform(ST_SetSRID(ab.geometry, 5179), 4326) ELSE ST_SetSRID(ab.geometry, 4326) END
              )
          )
        ORDER BY total_passengers DESC
    """
    
    try:
        df = execute_spatial_query(sql, {"search_name": f"%{clean_name}%"})
        if not df.empty:
            df["is_subway"] = True
            return df
    except Exception as e:
        print(f"⚠️ [db_tool] 특정 지하철역 쿼리 오류: {e}")

    return pd.DataFrame()


def search_stops_with_geom(stop_ids: list[str] | None = None, district_name: str | None = None) -> gpd.GeoDataFrame:
    if stop_ids:
        statement = text("SELECT stop_id, stop_name, gu_name, dong_name, housing_district_name, geometry FROM stop_admin_mapping WHERE stop_id IN :ids")
        statement = statement.bindparams(bindparam("ids", expanding=True))
        return gpd.read_postgis(statement, engine, geom_col="geometry", params={"ids": stop_ids})
    if district_name:
        return gpd.read_postgis(text("SELECT stop_id, stop_name, gu_name, dong_name, housing_district_name, geometry FROM stop_admin_mapping WHERE housing_district_name ILIKE :district"), engine, geom_col="geometry", params={"district": f"%{district_name}%"})
    return gpd.GeoDataFrame()


def get_district_boundary_geom(district_name: str) -> gpd.GeoDataFrame:
    clean_name = _clean_district_name(district_name)
    return gpd.read_postgis(
        text("SELECT admin_name, geometry FROM admin_boundary WHERE admin_level = 'housing_district' AND admin_name ILIKE :district"),
        engine,
        geom_col="geometry",
        params={"district": f"%{clean_name}%"}
    )


def get_stop_traffic_by_name(stop_name: str) -> pd.DataFrame:
    clean_name = stop_name.strip()
    
    sql = f"""
        SELECT m.stop_id, m.stop_name, m.dong_name, m.housing_district_name, 
               ST_AsText(
                   CASE 
                       WHEN ST_X(ST_Centroid(m.geometry)) > 1000 
                       THEN ST_Transform(ST_SetSRID(m.geometry, 5179), 4326)
                       ELSE ST_SetSRID(m.geometry, 4326)
                   END
               ) AS geometry,
               COALESCE(SUM(s.total_passengers), 0) AS total_passengers,
               COALESCE(SUM(s.total_boardings), 0) AS total_boardings,
               COALESCE(SUM(s.total_alightings), 0) AS total_alightings
        FROM stop_admin_mapping m
        LEFT JOIN bis_tcn_stop_mapping b ON m.stop_id = b.bis_stop_id AND {TRUSTED_MAPPING}
        LEFT JOIN summary_daily_stop_traffic s ON b.tcn_stop_id = s.stop_id
        WHERE m.stop_name ILIKE :stop_name
          AND m.geometry IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM admin_boundary ab
              WHERE ST_Intersects(
                  CASE WHEN ST_X(ST_Centroid(m.geometry)) > 1000 THEN ST_Transform(ST_SetSRID(m.geometry, 5179), 4326) ELSE ST_SetSRID(m.geometry, 4326) END,
                  CASE WHEN ST_X(ST_Centroid(ab.geometry)) > 1000 THEN ST_Transform(ST_SetSRID(ab.geometry, 5179), 4326) ELSE ST_SetSRID(ab.geometry, 4326) END
              )
          )
        GROUP BY m.stop_id, m.stop_name, m.dong_name, m.housing_district_name, m.geometry
        ORDER BY total_passengers DESC
    """
    return execute_spatial_query(sql, {"stop_name": f"%{clean_name}%"})

def get_district_to_subway_od(district_name: str, top_n: int = 200) -> pd.DataFrame:
    """
    탄현/탄현1 등 지정 구역 정류장에서 목적지(지하철역)로 가는 OD 통행 데이터를 조회합니다.
    """
    import re
    import pandas as pd
    from tools.db_tool import execute_query

    limit_clause = f"LIMIT {top_n}" if top_n and top_n > 0 else "LIMIT 200"
    clean_kw = district_name.replace("지구", "").replace("동", "").strip()
    base_kw = re.sub(r'\d+', '', clean_kw).strip() or clean_kw

    # 1차 시도: tcn_dwtcn_raw 이용 정류장 단위 OD
    sql_tcn = f"""
        SELECT 
            s.stop_name AS start_stop_name,
            COALESCE(s.housing_district_name, s.dong_name) AS start_district,
            COALESCE(sub.station || '역', e.stop_name, '목적지 정류장') AS end_stop_name,
            ST_X(s.geometry) AS start_lon,
            ST_Y(s.geometry) AS start_lat,
            COALESCE(ST_X(sub.geometry), ST_X(e.geometry)) AS end_lon,
            COALESCE(ST_Y(sub.geometry), ST_Y(e.geometry)) AS end_lat,
            SUM(COALESCE(CAST(f.user_cnt AS NUMERIC), 1)) AS total_passengers,
            COUNT(*) AS total_trips
        FROM tcn_dwtcn_raw f
        JOIN stop_admin_mapping s 
          ON CAST(f.on_sttn_id AS VARCHAR) = CAST(s.stop_id AS VARCHAR)
        LEFT JOIN subway_stations sub 
          ON CAST(f.off_sttn_id AS VARCHAR) = CAST(sub.station_id AS VARCHAR)
        LEFT JOIN stop_admin_mapping e 
          ON CAST(f.off_sttn_id AS VARCHAR) = CAST(e.stop_id AS VARCHAR)
        WHERE (s.housing_district_name LIKE '%{clean_kw}%' OR s.dong_name LIKE '%{clean_kw}%'
               OR s.housing_district_name LIKE '%{base_kw}%' OR s.dong_name LIKE '%{base_kw}%')
        GROUP BY 
            s.stop_name, s.housing_district_name, s.dong_name,
            sub.station, e.stop_name,
            s.geometry, sub.geometry, e.geometry
        ORDER BY total_passengers DESC
        {limit_clause};
    """
    try:
        df = execute_query(sql_tcn)
        if df is not None and not df.empty:
            df = df.dropna(subset=['start_lon', 'start_lat', 'end_lon', 'end_lat']).copy()
            if not df.empty:
                print(f"✅ [1차 정류장 OD 성공] {len(df)}건")
                return df
    except Exception as e:
        print(f"⚠️ [1차 tcn OD 조회 실패]: {e}")

    # 2차 시도 (폴백): summary_dong_od_flow
    sql_summary = f"""
        SELECT 
            f.start_dong AS start_stop_name,
            f.start_dong AS start_district,
            COALESCE(sub.station || '역', f.end_dong) AS end_stop_name,
            ST_X(ST_Centroid(s.geometry)) AS start_lon,
            ST_Y(ST_Centroid(s.geometry)) AS start_lat,
            COALESCE(ST_X(sub.geometry), ST_X(ST_Centroid(e.geometry))) AS end_lon,
            COALESCE(ST_Y(sub.geometry), ST_Y(ST_Centroid(e.geometry))) AS end_lat,
            SUM(COALESCE(f.total_passenger_count, f.trip_count, 1)) AS total_passengers,
            SUM(COALESCE(f.trip_count, 1)) AS total_trips
        FROM summary_dong_od_flow f
        LEFT JOIN admin_boundary s ON (s.admin_name LIKE '%' || REPLACE(f.start_dong, '동', '') || '%')
        LEFT JOIN admin_boundary e ON (e.admin_name LIKE '%' || REPLACE(f.end_dong, '동', '') || '%')
        LEFT JOIN subway_stations sub ON (f.end_dong LIKE '%' || REPLACE(sub.station, '역', '') || '%')
        WHERE (f.start_dong LIKE '%{base_kw}%' OR s.admin_name LIKE '%{base_kw}%')
        GROUP BY f.start_dong, f.end_dong, sub.station, s.geometry, e.geometry, sub.geometry
        ORDER BY total_passengers DESC
        {limit_clause};
    """
    try:
        df_fb = execute_query(sql_summary)
        if df_fb is not None and not df_fb.empty:
            df_fb = df_fb.dropna(subset=['start_lon', 'start_lat', 'end_lon', 'end_lat']).copy()
            print(f"✅ [2차 summary OD 폴백 성공] {len(df_fb)}건")
            return df_fb
    except Exception as e:
        print(f"❌ [2차 OD 폴백 실패]: {e}")

    return pd.DataFrame()