"""DB 연결 및 세션 관리 (SQLite + SQLAlchemy)."""

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'movie.db'}")

# SQLite는 기본적으로 스레드 간 커넥션 공유를 막으므로 check_same_thread=False 필요
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """SQLite는 외래키 제약을 기본으로 끄므로 커넥션마다 켜 준다.
    (영화 삭제 시 리뷰 ON DELETE CASCADE가 동작하려면 필수)"""
    if DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 의존성 주입용 DB 세션 제너레이터."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401  (테이블 등록 목적)

    Base.metadata.create_all(bind=engine)
