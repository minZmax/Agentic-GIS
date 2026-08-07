"""Gemini function-calling bridge for safe GIS analysis."""
from __future__ import annotations

import os
import re
import traceback
from dataclasses import dataclass

import pandas as pd

from tools.db_tool import (
    get_district_traffic,
    get_dong_od_flow,
    get_housing_district_summary,
    get_top_stops,
    execute_readonly_sql,
    UnsafeSQLError,
)
from tools.map_data import (
    get_district_geojson,
    get_housing_district_summary_geojson,
    get_od_flow_geojson,
    get_stops_geojson,
)


MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


@dataclass
class ToolResult:
    query_type: str
    geojson: dict
    data: pd.DataFrame

    def model_payload(self) -> dict:
        if isinstance(self.data, pd.DataFrame) and "geometry" in self.data.columns:
            clean_df = self.data.drop(columns=["geometry"], errors="ignore")
        else:
            clean_df = self.data

        return {
            "query_type": self.query_type,
            "row_count": len(clean_df),
            # 💡 최대 100개 데이터까지 LLM 요약 전달
            "rows": clean_df.head(100).where(pd.notnull(clean_df), None).to_dict(orient="records"),
        }


def _extract_limit(prompt: str, default: int = 10) -> int:
    """프롬프트 텍스트에서 숫자(예: '100개', '50개', '상위 20')를 감지하여 limit 값으로 변환"""
    match = re.search(r'(\d+)\s*(?:개|위|명|정류장)?', prompt)
    if match:
        try:
            val = int(match.group(1))
            return max(1, min(val, 100))
        except ValueError:
            pass
    return default


def _build_chart_data(data: pd.DataFrame | None) -> list[dict]:
    """DataFrame 분석 결과에서 Chart.js 렌더링용 상위 10개 라벨-수치 데이터 추출"""
    if data is None or not isinstance(data, pd.DataFrame) or data.empty:
        return []

    chart_list = []
    try:
        # 💡 정류장명(stop_name)을 최우선으로 탐색하도록 순서 변경
        label_col = None
        for col in ["stop_name", "housing_district_name", "start_dong", "admin_name"]:
            if col in data.columns:
                label_col = col
                break

        val_col = None
        for col in ["total_passengers", "total_trips", "total_boardings"]:
            if col in data.columns:
                val_col = col
                break

        if label_col and val_col:
            top_df = data.head(10)
            for _, row in top_df.iterrows():
                lbl = str(row.get(label_col, "")).strip()
                if label_col == "start_dong" and "end_dong" in data.columns:
                    end_lbl = str(row.get("end_dong", "")).strip()
                    lbl = f"{lbl} → {end_lbl}"
                
                val = float(row.get(val_col, 0) or 0)
                if lbl and val > 0:
                    chart_list.append({"label": lbl, "value": val})
    except Exception as e:
        print(f"⚠️ [gemini_agent] 차트 데이터 변환 오류: {e}")

    return chart_list


def execute_tool(name: str, arguments: dict, user_prompt: str = "") -> ToolResult:
    # 💡 프롬프트에 '100개' 등이 지정되어 있다면 인자값을 오버라이드
    prompt_limit = _extract_limit(user_prompt, default=10)
    
    if name == "get_top_stops":
        arg_limit = arguments.get("limit")
        limit = prompt_limit if (arg_limit is None or arg_limit == 10) else int(arg_limit)
        limit = max(1, min(limit, 100))
        
        data = get_top_stops(limit)
        return ToolResult("top_stops", get_stops_geojson(data), data)
        
    if name == "get_district_traffic":
        district = str(arguments.get("district_name", "")).strip()
        data = get_district_traffic(district)
        return ToolResult("housing_district", get_district_geojson(district), data)
        
    if name == "get_housing_district_summary":
        data = get_housing_district_summary()
        return ToolResult("housing_district", get_housing_district_summary_geojson(), data)
        
    if name == "get_dong_od_flow":
        start = str(arguments.get("start_dong", "")).strip() or None
        end = str(arguments.get("end_dong", "")).strip() or None
        limit = prompt_limit if arguments.get("limit") is None else int(arguments.get("limit", 10))
        data = get_dong_od_flow(start, end, limit)
        return ToolResult("od_flow", get_od_flow_geojson(data), data)

    if name == "run_sql_query":
        sql = str(arguments.get("sql", "")).strip()
        data = execute_readonly_sql(sql)  # UnsafeSQLError는 호출부(run_sql_query 클로저)에서 처리
        empty_geojson = {"type": "FeatureCollection", "features": []}
        return ToolResult("sql_result", empty_geojson, data)

    raise ValueError(f"허용되지 않은 GIS 도구입니다: {name}")


DB_SCHEMA_DESCRIPTION = """
[사용 가능한 테이블 - PostgreSQL/PostGIS, 반드시 아래 실제 컬럼명만 사용할 것]

- bis_routes(route_id, route_name, operator, route_type, direction, start_point, end_point,
  weekday_interval_min, weekday_first, weekday_last, sat_interval_min, sat_first, sat_last,
  sun_interval_min, sun_first, sun_last, holiday_interval_min, holiday_first, holiday_last, geometry)
  : BIS 버스 노선 마스터. route_type 예시값: '마을버스', '일반버스', '광역버스' 등 (정확한 값은 모르면
    SELECT DISTINCT route_type FROM bis_routes 로 먼저 확인 후 ILIKE '%키워드%'로 필터링할 것)

- bis_stops(stop_id, stop_name, seq, direction, geometry) : BIS 정류장 마스터 (노선별 정류장 순번 포함)

- route_stop_sequence(route_id, stop_id, seq, direction) : 노선(route_id)별 정류장(stop_id) 순서.
  bis_routes.route_id, bis_stops.stop_id 와 각각 조인 가능

- stop_admin_mapping(stop_id, stop_name, gu_name, dong_name, dong_code, housing_district_name, geometry)
  : BIS 정류장의 행정구역/택지지구 매핑. stop_id는 BIS 체계

- bis_tcn_stop_mapping(bis_stop_id, bis_stop_name, tcn_stop_id, tcn_stop_name, tcn_ars_no,
  tcn_sigungu, tcn_dong, distance_m, name_similarity, confidence_level, geometry)
  : BIS 정류장 ID <-> 교통카드(TCN) 정류장 ID 매핑 테이블.
  ⚠️ 매우 중요: BIS와 TCN은 서로 다른 stop_id 체계를 쓰므로 절대로 두 stop_id를 직접 비교/조인하면 안 됨.
  반드시 이 매핑 테이블을 거쳐야 하고, confidence_level IN ('EXACT','HIGH','MEDIUM') 조건을 항상 포함할 것

- summary_daily_stop_traffic(op_date, stop_id, stop_name, sigungu_name, dong_name,
  total_boardings, total_alightings, total_passengers)
  : 정류장별 일자별 교통카드 승하차 집계. 여기 stop_id는 TCN 체계 (BIS 정류장과 조인하려면
  bis_tcn_stop_mapping.tcn_stop_id 를 거칠 것)

- summary_dong_od_flow(op_date, start_sigungu, start_dong, end_sigungu, end_dong,
  trip_count, total_passenger_count, avg_trip_distance_km, avg_trip_time_min)
  : 행정동 간 OD(출발-도착) 통행 집계

- admin_boundary(admin_name, admin_code, base_date, admin_level, geometry)
  : 행정경계. admin_level 값: 'si'(시), 'gu'(구), 'dong'(행정동), 'housing_district'(택지지구) 등

- subway_stations(STN_ID, STN_KOR, LINE_ID, LINE_NM, LAT, LON, OPERATOR, ADDR, geometry)
  : 지하철역 마스터 (컬럼명이 대문자인 점 주의)

[참고: 원천(raw) 적재 테이블 - 매우 크고 느릴 수 있음, 가급적 위의 summary 테이블을 우선 사용]
tcn_dwtcn_raw, tcn_route_raw, tcn_routesttn_raw, tcn_sttn_raw (교통카드 원본 데이터)

[SQL 작성 규칙]
- PostgreSQL 문법을 사용할 것 (예: ILIKE, COUNT(DISTINCT ...))
- 반드시 SELECT 또는 WITH ... SELECT 로 시작하는 단일 조회문만 작성할 것
- 정확한 값(예: route_type)을 모르면 먼저 DISTINCT로 실제 값을 확인하는 탐색 쿼리를 실행해도 됨
- 결과 행이 많을 수 있는 질문에는 LIMIT을 적절히 포함할 것
"""

SYSTEM_INSTRUCTION = f"""당신은 고양시 대중교통 GIS/데이터 분석가입니다.

사용자 질문에 답하기 위해 아래 도구 중 가장 적합한 것을 호출하세요:

[지도 시각화가 필요한 질문 -> 전용 도구 사용]
1. 특정 지구(창릉, 삼송, 향동, 일산, 화정, 탄현 등)의 정류장/이용량을 지도에 보여달라는 질문
   -> district_traffic(district_name=...)
2. 고양시 전체 택지지구를 비교해서 지도에 보여달라는 질문 -> housing_district_summary()
3. 이용량 상위 N개 정류장을 지도에 보여달라는 질문 -> top_stops(limit=N)
4. 행정동간 통행(OD) 흐름을 지도에 보여달라는 질문 -> dong_od_flow(...)

[그 외 모든 질문 -> run_sql_query(sql=...) 사용]
위 4개 도구로 해결되지 않는 질문(개수 세기, 통계, 조건 필터, 비교, 순위 등 지도 시각화가
필수는 아닌 모든 질문)은 아래 스키마를 참고하여 SELECT 쿼리를 직접 작성해 run_sql_query로 실행하세요.
예: "마을버스 노선이 몇 개야?", "탄현동 정류장은 총 몇 개야?", "OO노선은 몇 개 정류장을 지나가?"

{DB_SCHEMA_DESCRIPTION}

결과는 항상 한국어로 자연스럽게 요약하고, 사용자가 요청한 개수(N개)가 있다면 그대로 반영하세요.
도구 호출 결과가 비어 있으면 "조회된 데이터가 없습니다"라고 솔직하게 답하세요."""


def query_with_gemini(prompt: str) -> dict:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("google-genai 패키지가 설치되지 않았습니다.") from exc

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다.")

    client = genai.Client(api_key=api_key)
    last_result: ToolResult | None = None

    def top_stops(limit: int = 10) -> dict:
        """고양시 정류장 교통카드 이용량 상위 N개를 조회한다."""
        nonlocal last_result
        last_result = execute_tool("get_top_stops", {"limit": limit}, user_prompt=prompt)
        return last_result.model_payload()

    def district_traffic(district_name: str) -> dict:
        """특정 고양시 택지지구의 개별 정류장 이용량을 조회한다."""
        nonlocal last_result
        last_result = execute_tool("get_district_traffic", {"district_name": district_name}, user_prompt=prompt)
        return last_result.model_payload()

    def housing_district_summary() -> dict:
        """고양시 모든 택지지구 전체 이용량을 일괄 비교한다."""
        nonlocal last_result
        last_result = execute_tool("get_housing_district_summary", {}, user_prompt=prompt)
        return last_result.model_payload()

    def dong_od_flow(start_dong: str = "", end_dong: str = "", limit: int = 10) -> dict:
        """행정동 사이 버스 OD 통행량을 조회한다."""
        nonlocal last_result
        last_result = execute_tool("get_dong_od_flow", {"start_dong": start_dong, "end_dong": end_dong, "limit": limit}, user_prompt=prompt)
        return last_result.model_payload()

    def run_sql_query(sql: str) -> dict:
        """전용 도구(top_stops, district_traffic, housing_district_summary, dong_od_flow)로
        해결되지 않는 질문에 사용한다. 시스템 지침에 안내된 DB 스키마를 참고하여 작성한
        PostgreSQL SELECT 조회문을 실행하고 결과를 반환한다. 개수 세기, 통계, 조건 필터,
        비교/순위 등 지도 시각화가 필수는 아닌 질문에 사용하면 된다."""
        nonlocal last_result
        try:
            last_result = execute_tool("run_sql_query", {"sql": sql}, user_prompt=prompt)
            return last_result.model_payload()
        except UnsafeSQLError as exc:
            # 검증 실패는 last_result를 갱신하지 않고, Gemini에게 실패 사유를 알려 재시도를 유도
            return {"error": str(exc), "row_count": 0, "rows": []}
        except Exception as exc:
            return {"error": f"쿼리 실행에 실패했습니다: {exc}", "row_count": 0, "rows": []}

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                tools=[top_stops, district_traffic, housing_district_summary, dong_od_flow, run_sql_query],
            ),
        )

        if last_result is None:
            from tools.gis_agent import query_deterministic
            fallback_res = query_deterministic(prompt)
            fallback_res.setdefault("chart_data", [])
            return fallback_res

        return {
            "query_type": last_result.query_type,
            "text": response.text or "분석 결과를 요약하지 못했습니다.",
            "geojson": last_result.geojson,
            "chart_data": _build_chart_data(last_result.data),
        }

    except Exception as exc:
        print("❌ [query_with_gemini] 예외 발생으로 인한 로컬 모드 폴백:")
        traceback.print_exc()
        from tools.gis_agent import query_deterministic
        fallback_res = query_deterministic(prompt)
        fallback_res.setdefault("chart_data", [])
        return fallback_res