"""Goyang Agentic GIS web application."""
from __future__ import annotations

import os
import re
from flask import Flask, jsonify, request, send_from_directory
from flask_compress import Compress
from dotenv import load_dotenv  # 💡 1. load_dotenv 임포트

# 💡 2. .env 파일의 환경변수 읽기
load_dotenv()

# 💡 3. 실행 시 API 키 로드 여부 출력 (터미널 확인용)
gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
print(f"[System Check] Gemini API Key Status: {'LOADED' if gemini_key else 'MISSING!'}")

app = Flask(__name__, static_folder="static", static_url_path="/static")

app.config["COMPRESS_MIN_SIZE"] = 1024
app.config["COMPRESS_MIMETYPES"] = [
    "text/html", "text/css", "text/xml",
    "application/json", "application/javascript", "application/geo+json",
]
Compress(app)


@app.get("/")
def index():
    if os.path.exists("index.html"): return send_from_directory(".", "index.html")
    elif os.path.exists("static/index.html"): return send_from_directory("static", "index.html")
    elif os.path.exists("templates/index.html"): return send_from_directory("templates", "index.html")
    return "index.html 파일을 찾을 수 없습니다.", 404


@app.get("/api/health")
def health():
    from tools.db_tool import database_is_available
    available, detail = database_is_available()
    return jsonify({"ok": available, "detail": detail}), 200 if available else 503


@app.get("/api/layers/default")
def default_layers():
    from tools.map_data import get_default_layers
    try:
        data = get_default_layers()
        response = jsonify(data)
        response.headers["Cache-Control"] = "public, max-age=600"
        return response
    except Exception:
        return jsonify({"error": "기본 레이어 로드 실패"}), 500


@app.post("/api/chat")
def chat():
    from tools.db_tool import get_district_to_subway_od
    from tools.map_data import get_district_od_combined_geojson
    from tools.gis_agent import query_agent

    body = request.get_json(silent=True) or {}
    prompt = str(body.get("prompt", "")).strip()

    if not prompt:
        return jsonify({"text": "질문을 입력해 주세요.", "query_type": "error", "geojson": None}), 400

    # 1. 명확한 OD/통행패턴 키워드가 있는 경우에만 OD 패스트패스 실행 (단순 '지하철' 제외)
    is_od_query = any(kw in prompt for kw in ["OD", "od", "통행패턴", "통행 패턴", "목적통행", "통행흐름", "통행 흐름"])

    if is_od_query:
        try:
            # 지구명 추출 (탄현1지구 -> 탄현1)
            district_keywords = ["탄현1", "탄현2", "탄현", "덕은", "삼송", "원흥", "지축", "향동", "식사", "풍동", "운정", "일산"]
            # target_district = "탄현"
            for kw in district_keywords:
                if kw in prompt:
                    target_district = kw
                    break

            top_n_match = re.search(r'(?:상위|top)\s*(\d+)', prompt, re.IGNORECASE)
            top_n = int(top_n_match.group(1)) if top_n_match else 200

            od_df = get_district_to_subway_od(target_district, top_n=top_n)

            if od_df.empty:
                return jsonify({
                    "text": f"<b>{target_district}</b> 구역의 OD 통행 데이터가 없습니다.",
                    "geojson": {"type": "FeatureCollection", "features": []},
                    "query_type": "od_flow",
                    "chart_data": []
                })

            combined_geojson = get_district_od_combined_geojson(target_district, od_df)

            # 차트용 데이터 (정류장 ➔ 목적지 중복 합산)
            chart_dict = {}
            for _, row in od_df.iterrows():
                s_label = str(row.get('start_stop_name') or '기점')
                e_label = str(row.get('end_stop_name') or '도착지')
                pair_key = f"{s_label} ➔ {e_label}"
                passengers = int(row.get('total_passengers', 0) or row.get('total_trips', 0))
                chart_dict[pair_key] = chart_dict.get(pair_key, 0) + passengers

            sorted_chart = sorted(chart_dict.items(), key=lambda x: x[1], reverse=True)[:10]
            chart_data = [{"label": k, "value": v} for k, v in sorted_chart]

            limit_text = f"상위 {top_n}개" if top_n_match else f"전체 패턴 (총 {len(od_df)}개)"
            return jsonify({
                "text": (
                    f"<b>{target_district} 버스 정류장 ➔ 주요 지하철역/목적지 OD 통행 패턴</b> 분석 결과입니다.<br>"
                    f"<small>• 조회 조건: {limit_text}<br>"
                    f"• 구역 경계 + 정류장 마커 + 반화살표 OD 통행선 통합 표시</small>"
                ),
                "geojson": combined_geojson,
                "query_type": "od_flow",
                "chart_data": chart_data
            })
        except Exception as exc:
            app.logger.exception("OD 질의 패스트패스 처리 중 오류")

    # 2. 단순 지하철역 수요 및 기타 질의는 GIS Agent로 넘겨 정상 처리
    try:
        result = query_agent(prompt)
        return jsonify(result)
    except Exception as exc:
        app.logger.exception("GIS query failed")
        return jsonify({
            "text": "분석 처리 중 오류가 발생했습니다.",
            "query_type": "error",
            "geojson": {"type": "FeatureCollection", "features": []},
        }), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)