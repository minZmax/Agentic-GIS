<<<<<<< HEAD
# 고양시 Agentic GIS MVP

PostgreSQL/PostGIS에 적재한 고양시 행정구역, 버스 노선·정류장, 교통카드 데이터를 자연어로 조회하고 Leaflet 지도에 함께 표시하는 웹 애플리케이션입니다.

## 실행

1. `.env`에 DB 접속 정보를 설정합니다. 비밀번호와 API 키는 저장소에 커밋하지 마세요.

```env
GEMINI_API_KEY=AI_Studio에서_발급한_키
GEMINI_MODEL=gemini-2.5-flash
```
2. Python 3.11~3.13 환경에서 의존성을 설치합니다.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

브라우저에서 `http://localhost:5000`을 엽니다.

## 현재 분석 도구

- 정류장 이용량 상위 N개
- 택지지구별 이용량 및 특정 지구의 정류장
- 행정동 간 OD 통행량

각 응답은 표와 GeoJSON을 동시에 반환하며, 클라이언트가 이를 동적 Leaflet 레이어로 렌더링합니다.

## 필요한 PostGIS 테이블

`stop_admin_mapping`, `bis_tcn_stop_mapping`, `summary_daily_stop_traffic`, `summary_dong_od_flow`, `admin_boundary`

## Gemini LLM 에이전트

`GEMINI_API_KEY`가 설정되면 Gemini가 질문에 맞는 분석 도구를 선택하고 결과를 한국어로 요약합니다. 키가 없으면 기존의 규칙 기반 분석기가 동작합니다. `tools/gemini_agent.py`는 임의 SQL을 허용하지 않으며, 모델에는 최대 30개 집계 행만 전달합니다. 새 분석 기능은 파라미터화된 DB 함수와 GeoJSON 변환기를 추가한 뒤, 이 파일의 허용 도구 목록에 등록하세요.
=======
# Agentic-GIS
자연어로 질문 시, DB를 읽어들여서 답변(표) 및 시각화(지도) 하는 프로그램
>>>>>>> 7367f1f64d2f84799af7aaeaa3ed62a58564700b
