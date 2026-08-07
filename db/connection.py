"""PostgreSQL/PostGIS connection factory."""
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

# 프로젝트 루트 폴더의 .env 파일을 절대 경로로 정확히 로드
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def get_engine():
    # 환경변수가 없을 경우 대비해 기본값(Fallback) 설정
    db_user = os.getenv("DB_USER") or os.getenv("POSTGRES_USER", "postgres")
    db_pass = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD", "1234")
    db_host = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST", "localhost")
    db_port = int(os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT", "5432"))
    db_name = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB", "goyang")  # 기본값: goyang

    url = URL.create(
        "postgresql+psycopg2",
        username=db_user,
        password=db_pass,
        host=db_host,
        port=db_port,
        database=db_name,
    )
    
    return create_engine(url, pool_pre_ping=True, future=True)