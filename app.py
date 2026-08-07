"""Goyang Agentic GIS web application."""
from __future__ import annotations

import os

from flask import Flask, jsonify, request, send_from_directory
from flask_compress import Compress

app = Flask(__name__)

# Gzip 압축 최적화 설정 (1KB 이상 응답 자동 압축)
app.config["COMPRESS_MIN_SIZE"] = 1024
app.config["COMPRESS_MIMETYPES"] = [
    "text/html",
    "text/css",
    "text/xml",
    "application/json",
    "application/javascript",
    "application/geo+json",
]
Compress(app)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    """Expose database readiness without leaking connection details."""
    from tools.db_tool import database_is_available

    available, detail = database_is_available()
    return jsonify({"ok": available, "detail": detail}), 200 if available else 503


@app.get("/api/layers/default")
def default_layers():
    """Reference layers displayed when the map is first opened."""
    from tools.map_data import get_default_layers

    # 1. BBOX 파라미터 파싱 (예: ?bbox=126.8,37.5,127.0,37.7)
    bbox_raw = request.args.get("bbox")
    bbox = None
    if bbox_raw:
        try:
            bbox = [float(coord.strip()) for coord in bbox_raw.split(",")]
            if len(bbox) != 4:
                bbox = None
        except ValueError:
            bbox = None

    try:
        # get_default_layers 함수가 bbox 인자를 지원하는지 하위 호환 체크
        try:
            data = get_default_layers(bbox=bbox) if bbox else get_default_layers()
        except TypeError:
            data = get_default_layers()

        response = jsonify(data)
        # 2. 브라우저 캐싱 적용 (10분)
        response.headers["Cache-Control"] = "public, max-age=600"
        return response

    except RuntimeError as exc:
        app.logger.exception("GIS/LLM query failed")
        return jsonify({
            "text": f"분석 엔진 오류: {exc}",
            "query_type": "error",
            "geojson": {"type": "FeatureCollection", "features": []},
        }), 503
    except Exception:
        app.logger.exception("Failed to load default map layers")
        return jsonify({"error": "기본 지도 레이어를 불러오지 못했습니다."}), 500


@app.post("/api/chat")
def chat():
    from tools.gis_agent import query_agent

    body = request.get_json(silent=True) or {}
    prompt = str(body.get("prompt", "")).strip()
    if not prompt:
        return jsonify({"text": "질문을 입력해 주세요.", "query_type": "error", "geojson": None}), 400

    try:
        result = query_agent(prompt)
        return jsonify(result)
    except Exception as exc:
        app.logger.exception("GIS query failed")
        message = str(exc)
        if "RESOURCE_EXHAUSTED" in message or "quota" in message.lower():
            text = "Gemini 무료 요청 한도에 도달했습니다. 잠시 후 다시 시도해 주세요."
            status = 429
        else:
            text = "분석 중 오류가 발생했습니다. PostgreSQL/PostGIS 연결과 테이블 적재 상태를 확인해 주세요."
            status = 500
        return jsonify({
            "text": text,
            "query_type": "error",
            "geojson": {"type": "FeatureCollection", "features": []},
        }), status


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)