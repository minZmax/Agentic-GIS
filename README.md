# 🌍 고양시 Agentic GIS

> 자연어로 질문하면 PostGIS 데이터를 분석하여 **표 + 지도 시각화**로 답변하는 AI 기반 GIS 웹 애플리케이션

PostgreSQL/PostGIS에 적재한 고양시 행정구역, 버스 노선·정류장, 교통카드 OD 데이터를 자연어로 조회하고 Leaflet 지도에 함께 표시합니다.

---

## 🚀 Quick Start (Docker — 권장)

**사전 요구사항**: [Docker Desktop](https://www.docker.com/products/docker-desktop/) 설치 및 실행

```bash
# 1. 저장소 클론
git clone https://github.com/minZmax/Agentic-GIS.git
cd Agentic-GIS

# 2. 환경 변수 설정 (.env 생성)
cp .env.example .env
# .env 파일을 열어 GEMINI_API_KEY 를 본인의 키로 입력 (Google AI Studio에서 무료 발급 가능)
# ※ API 키가 없어도 규칙 기반(Rule-based) 분석 모드로 기본 조회 및 지도 시각화가 정상 동작합니다.

# 3. Docker 빌드 & 실행 (DB 시드 데이터 약 8MB 자동 복원)
docker compose up --build

# 4. 브라우저에서 접속
#    http://localhost:5000
```

> **참고**: 최초 실행 시 PostGIS 컨테이너가 시드 데이터를 복원하는 데 약 30초~1분 소요됩니다. `agentic-gis-web` 컨테이너 로그에 `Gemini API Key Status: LOADED` (또는 키 미입력 시 `MISSING!`) 가 출력되면 준비 완료입니다.

### 종료 & 데이터 초기화

```bash
# 컨테이너 종료
docker compose down

# DB 볼륨까지 완전 삭제 후 초기 상태로 재시작 (시드 데이터 재복원)
docker compose down -v
docker compose up --build
```

---

## 🖥️ 로컬 개발 환경 실행

PostgreSQL/PostGIS가 이미 로컬에 설치되어 있고, DB에 데이터가 적재되어 있는 경우:

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

---

## 📁 프로젝트 구조

```
Agentic-GIS/
├── app.py                  # Flask 메인 서버
├── docker-compose.yml      # Docker Compose 오케스트레이션
├── Dockerfile              # Python 웹 앱 컨테이너 빌드 파일
├── docker/init-db/         # PostGIS 자동 초기화 스크립트 & 시드 덤프
├── db/connection.py        # DB 커넥션 풀 및 팩토리
├── tools/
│   ├── db_tool.py          # 안전한 파라미터화 DB 쿼리 함수
│   ├── gis_agent.py        # 규칙 기반 GIS 분석 에이전트 & 폴백
│   ├── gemini_agent.py     # Gemini LLM 에이전트
│   ├── map_data.py         # GeoJSON 변환기
│   └── map_tool.py         # 지도 생성 유틸리티
├── static/
│   ├── index.html          # Leaflet 기반 반응형 대시보드
│   ├── css/                # 스타일시트
│   └── js/app.js           # 프론트엔드 통신 및 지도 렌더러
├── pipeline/               # 데이터 ETL/전처리 파이프라인
├── .env.example            # 환경 변수 설정 템플릿
├── .gitattributes          # 크로스 플랫폼 줄바꿈(LF) 보장
└── requirements.txt        # Python 의존성 패키지 목록
```