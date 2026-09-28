<<<<<<< HEAD
# 고양시 Agentic GIS MVP

PostgreSQL/PostGIS에 적재한 고양시 행정구역, 버스 노선·정류장, 교통카드 데이터를 자연어로 조회하고 Leaflet 지도에 함께 표시하는 웹 애플리케이션입니다.

### 종료 & 데이터 초기화

```bash
# 종료
docker compose down

# DB 볼륨까지 완전 삭제 후 재시작 (시드 데이터 재복원)
docker compose down -v
docker compose up --build
```

---

## 🖥️ 로컬 개발 환경 실행

PostgreSQL/PostGIS가 이미 설치되어 있고, DB에 데이터가 적재되어 있는 경우:

1. `.env` 파일에 DB 접속 정보를 설정합니다.

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=goyang
DB_USER=postgres
DB_PASSWORD=1234
GEMINI_API_KEY=AI_Studio에서_발급한_키
GEMINI_MODEL=gemini-3.1-flash-lite
```

2. Python 3.11+ 환경에서 의존성을 설치하고 실행합니다.

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

브라우저에서 `http://localhost:5000`을 엽니다.

---

## 📊 분석 기능

| 기능 | 설명 |
|------|------|
| **정류장 이용량 Top-N** | 고양시 관내 버스 정류장 이용량 상위 N개 조회 |
| **택지지구별 분석** | 택지지구별 이용량 비교 및 특정 지구의 정류장 분석 |
| **OD 통행 패턴** | 행정동/정류장 간 기종점 통행량 분석 |
| **지하철역 수요** | 고양시 관내 지하철역 수송 수요 분석 |
| **자연어 질의** | Gemini AI가 질문에 맞는 분석 도구를 자동 선택 |

각 응답은 **표 + GeoJSON**을 동시에 반환하며, 클라이언트가 이를 동적 Leaflet 레이어로 렌더링합니다.

---

## 🗄️ PostGIS 테이블 구조

### 핵심 테이블 (Docker 시드 데이터에 포함)
- `stop_admin_mapping` — 정류장-행정동 매핑
- `bis_tcn_stop_mapping` — BIS-TCN 정류장 매핑
- `summary_daily_stop_traffic` — 일별 정류장 승하차 집계
- `summary_dong_od_flow` — 행정동 간 OD 통행 집계
- `admin_boundary` — 행정구역 경계 (geometry)
- `subway_stations` — 지하철역 정보
- 기타 코드 테이블 (`cd_*`)

### 대용량 테이블 (Docker 시드에서 제외)
- `tcn_dwtcn_raw` (1.6GB) — 교통카드 원시 통행 데이터
- `tcn_routesttn_raw`, `tcn_sttn_raw`, `tcn_route_raw`

> 대용량 raw 테이블이 없어도 요약 테이블 기반으로 **대부분의 분석 기능이 정상 동작**합니다. 정류장 단위 OD 분석 시에는 자동으로 `summary_dong_od_flow` 폴백 경로를 사용합니다.

---

## 🤖 Gemini LLM 에이전트

`GEMINI_API_KEY`가 설정되면 Gemini가 질문에 맞는 분석 도구를 선택하고 결과를 한국어로 요약합니다. 키가 없으면 기존의 규칙 기반 분석기가 동작합니다. `tools/gemini_agent.py`는 임의 SQL을 허용하지 않으며, 모델에는 최대 30개 집계 행만 전달합니다. 새 분석 기능은 파라미터화된 DB 함수와 GeoJSON 변환기를 추가한 뒤, 이 파일의 허용 도구 목록에 등록하세요.