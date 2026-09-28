#!/bin/bash
set -e

echo "=== PostGIS 확장 활성화 ==="
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE EXTENSION IF NOT EXISTS postgis;"

DUMP_FILE="/docker-entrypoint-initdb.d/goyang_seed.dump"

if [ -f "$DUMP_FILE" ]; then
    echo "=== DB 시드 데이터 복원 시작 ==="
    pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        --no-owner --no-privileges \
        --if-exists --clean \
        "$DUMP_FILE" || true
    echo "=== DB 시드 데이터 복원 완료 ==="
else
    echo "⚠️  시드 덤프 파일 미발견: $DUMP_FILE"
fi
