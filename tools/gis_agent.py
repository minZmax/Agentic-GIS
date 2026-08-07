"""A deterministic GIS analysis agent for the first product iteration."""
from __future__ import annotations

import os
import re
import pandas as pd

from tools.db_tool import (
    get_district_traffic, 
    get_dong_od_flow, 
    get_housing_district_summary, 
    get_top_stops,
    get_stop_traffic_by_name,
    get_subway_traffic_by_name,
    get_all_subway_traffic
)

from tools.map_data import (
    get_district_geojson,
    get_housing_district_summary_geojson,
    get_od_flow_geojson,
    get_stops_geojson,
)

KNOWN_DONGS = ["주엽", "정발산", "일산", "마두", "백석", "식사", "탄현", "중산", "풍동", "대화", "덕이", "가좌", "화정", "행신", "능곡", "행주", "원당", "성사", "고양동", "관산"]
KNOWN_DISTRICTS = ["창릉", "덕은", "원흥", "삼송", "지축", "향동", "일산", "화정", "능곡", "탄현", "덕이", "장항", "대곡", "가좌", "식사", "풍동", "중산", "백석", "행신"]


def _markdown_table(frame: pd.DataFrame, maximum_rows: int = 100) -> str:
    if frame is None or frame.empty:
        return "조회 조건에 맞는 데이터가 없습니다."
    
    clean_df = frame.drop(columns=["geometry"], errors="ignore") if "geometry" in frame.columns else frame
    display = clean_df.head(maximum_rows).copy()
    
    for column in display.select_dtypes(include="number"):
        display[column] = display[column].map(lambda v: f"{v:,.0f}" if pd.notna(v) else "-")
    return display.to_markdown(index=False)


def _find_terms(prompt: str, candidates: list[str]) -> list[str]:
    return [term for term in candidates if term in prompt]


def _extract_district_name(prompt: str) -> str | None:
    for dist in KNOWN_DISTRICTS:
        if dist in prompt:
            return dist

    match = re.search(r'([가-힣]{2,8})\s*(?:지구|신도시|지역|택지)', prompt)
    if match:
        extracted = match.group(1).replace("고양시", "").replace("고양", "").strip()
        if extracted and extracted not in ("택지", "버스", "전체", "모든"):
            return extracted

    return None


def _build_chart_data(data: pd.DataFrame | None) -> list[dict]:
    if data is None or not isinstance(data, pd.DataFrame) or data.empty:
        return []

    chart_list = []
    try:
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
    except Exception:
        pass

    return chart_list


def query_deterministic(prompt: str) -> dict:
    lower = prompt.lower()

    # '3호선', '1호선' 등의 노선 번호 단어를 제거한 후 개수(limit) 추출
    clean_limit_prompt = re.sub(r'\d+호선', '', prompt)
    match = re.search(r'(\d+)\s*(?:개|위|명|정류장)?', clean_limit_prompt)
    limit = int(match.group(1)) if match else 10
    limit = max(1, min(limit, 100))

    # 1. 지하철/철도 관련 요청 분기 정교화
    subway_keywords = ["지하철", "지하철역", "3호선", "경의중앙선", "경의선", "전철", "gtx"]
    is_subway_req = any(kw in lower for kw in subway_keywords)

    # 特定 역 이름 추출 정교화 (일반 단어 및 숫자 오매칭 방지)
    target_name = ""
    stop_match = re.search(r'([가-힣0-9a-zA-Z]+)(?:역|정류장)', prompt)
    if stop_match:
        raw_target = stop_match.group(1)
        raw_target = re.sub(r'\d+호선', '', raw_target)
        for kw in ["지하철", "경의중앙선", "경의선", "전철", "gtx", "고양시", "고양", "상위", "이용량", "수요", "모든", "전체"]:
            raw_target = raw_target.replace(kw, "")
        raw_target = raw_target.strip()
        
        # '10개', '상위' 등 숫자나 일반 지시어인 경우 특정 역 검색 대상에서 제외
        if raw_target and raw_target not in ("상위", "모든", "전체", "개") and not raw_target.isdigit():
            target_name = raw_target

    # 💡 [케이스 A] 특정 역/정류장이 명시된 경우 ("3호선 대화역", "탄현역" 등)
    if target_name:
        if is_subway_req:
            data = get_subway_traffic_by_name(target_name)
            title = f"지하철 {target_name}역 수송 수요 분석"
        else:
            data = get_stop_traffic_by_name(target_name)
            title = f"{target_name} 주변 버스 정류장 이용량 분석"
            
        if data is not None and not data.empty:
            return {
                "query_type": "top_stops",
                "text": f"### {title}\n\n{_markdown_table(data)}",
                "geojson": get_stops_geojson(data),
                "chart_data": _build_chart_data(data)
            }

    # 💡 [케이스 B] 특정 역 없이 일반 지하철 요청인 경우 ("고양시 지하철 이용량 상위 10개 역을 보여줘", "지하철역 수요" 등)
    if is_subway_req:
        subway_data = get_all_subway_traffic(limit)
        title = f"고양시 관내 지하철역 수송 수요 (상위 {len(subway_data)}개 역)" if not subway_data.empty else "고양시 관내 지하철역 수송 수요"
        
        # 지하철 요청인 경우 버스 정류장 fallback으로 절대 빠지지 않도록 즉시 반환
        return {
            "query_type": "top_stops",
            "text": f"### {title}\n\n{_markdown_table(subway_data)}",
            "geojson": get_stops_geojson(subway_data),
            "chart_data": _build_chart_data(subway_data)
        }

    clean_prompt = prompt.replace("고양시", "").replace("고양 시", "")
    dongs = _find_terms(clean_prompt, KNOWN_DONGS)

    # 2. OD 통행 분석
    has_od_keyword = any(kw in lower for kw in ("od", "통행", "출발", "도착", "이동량", "흐름"))
    if has_od_keyword or len(dongs) >= 2:
        start_dong = dongs[0] if len(dongs) >= 1 else None
        end_dong = dongs[1] if len(dongs) >= 2 else None
        
        data = get_dong_od_flow(start_dong, end_dong, limit)
        
        title = "고양시 행정동간 버스 OD 통행 분석"
        if start_dong and end_dong:
            title = f"{start_dong} → {end_dong} 버스 OD 통행 분석"
        elif start_dong:
            title = f"{start_dong} 출발 버스 OD 통행 분석"

        return {
            "query_type": "od_flow",
            "text": f"### {title}\n\n" + _markdown_table(data),
            "geojson": get_od_flow_geojson(data),
            "chart_data": _build_chart_data(data)
        }

    # 3. 택지지구 / 지역 분석
    target_district = _extract_district_name(prompt)
    if target_district:
        data = get_district_traffic(target_district)
        text = f"### {target_district}지구 정류장 및 이용량 분석\n\n{_markdown_table(data)}"
        geojson = get_district_geojson(target_district)
        return {
            "query_type": "housing_district", 
            "text": text, 
            "geojson": geojson,
            "chart_data": _build_chart_data(data)
        }
    
    if any(word in lower for word in ("택지", "지구", "신도시", "비교")):
        data = get_housing_district_summary()
        text = f"### 고양시 택지지구별 버스 이용량 요약\n\n{_markdown_table(data)}"
        geojson = get_housing_district_summary_geojson()
        return {
            "query_type": "housing_district", 
            "text": text, 
            "geojson": geojson,
            "chart_data": _build_chart_data(data)
        }

    # 4. 상위 정류장 분석 (순수 버스 정류장 전용 Fallback)
    data = get_top_stops(limit)
    mode_label = "버스 정류장"
    title = f"고양시 {mode_label} 이용량 상위 {len(data)}곳"
    return {
        "query_type": "top_stops", 
        "text": f"### {title}\n\n{_markdown_table(data)}", 
        "geojson": get_stops_geojson(data),
        "chart_data": _build_chart_data(data)
    }


def query_agent(prompt: str) -> dict:
    if os.getenv("GEMINI_API_KEY"):
        from tools.gemini_agent import query_with_gemini
        try:
            return query_with_gemini(prompt)
        except Exception as exc:
            result = query_deterministic(prompt)
            if "RESOURCE_EXHAUSTED" in str(exc) or "quota" in str(exc).lower():
                note = "Gemini 무료 요청 한도에 도달해 이번 요청은 로컬 분석 모드로 처리했습니다."
            else:
                note = "Gemini 응답을 사용할 수 없어 이번 요청은 로컬 분석 모드로 처리했습니다."
            result["text"] = f"> {note}\n\n{result['text']}"
            return result
            
    return query_deterministic(prompt)