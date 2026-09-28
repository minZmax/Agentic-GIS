# ─────────────────────────────────────────────
# Agentic-GIS  ·  Python Web App
# ─────────────────────────────────────────────
FROM python:3.11-slim

# PostGIS 클라이언트 & 빌드 의존성 (psycopg2, pyproj, GDAL 등)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libgdal-dev \
        libgeos-dev \
        libproj-dev \
        gdal-bin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 설치 (캐시 레이어 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# Flask 포트
EXPOSE 5000

# gunicorn 프로덕션 서버로 실행
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "app:app"]
