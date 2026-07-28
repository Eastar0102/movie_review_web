"""Streamlit Cloud 배포용 — FastAPI 백엔드를 같은 프로세스에서 기동한다.

Streamlit Cloud는 앱 프로세스 하나만 띄우므로, 별도 백엔드 호스팅 없이 서비스를 완성하려면
uvicorn을 백그라운드 스레드로 함께 실행해야 한다. 데이터는 여전히 전부 FastAPI + SQLite가
관리하고 Streamlit은 HTTP로만 접근한다.

`API_URL`(환경변수 또는 secrets)이 지정돼 있으면 이 모듈은 쓰이지 않고 외부 백엔드를 호출한다.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).resolve().parent
BACKEND_DIR = FRONTEND_DIR.parent / "backend"
SEED_DB = BACKEND_DIR / "seed" / "movie.db"
BOOT_TIMEOUT = 90  # 초


def _free_port() -> int:
    """사용 중이지 않은 포트를 골라 로컬 uvicorn과 충돌하지 않게 한다."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _prepare_database() -> str:
    """쓰기 가능한 경로에 DB를 준비하고 DATABASE_URL을 만든다.

    Streamlit Cloud의 소스 디렉터리는 재배포마다 초기화되므로 임시 디렉터리를 쓰고,
    비어 있으면 저장소에 커밋된 시드 DB(영화 50편 · 리뷰 500개)를 복사해 넣는다.
    """
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]

    data_dir = Path(tempfile.gettempdir()) / "movie_review_service"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "movie.db"
    if not db_path.exists() and SEED_DB.exists():
        shutil.copy2(SEED_DB, db_path)
        logger.info("시드 DB를 %s 로 복사했습니다.", db_path)
    return f"sqlite:///{db_path}"


def start() -> str:
    """백엔드를 기동하고 접속 주소를 반환한다."""
    import uvicorn  # noqa: PLC0415

    os.environ["DATABASE_URL"] = _prepare_database()
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    from app.main import app  # noqa: PLC0415  (sys.path 등록 후에 import해야 한다)

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    # uvicorn은 메인 스레드가 아니면 시그널 핸들러 등록을 건너뛰므로 스레드 실행이 가능하다.
    threading.Thread(target=uvicorn.Server(config).run, daemon=True).start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + BOOT_TIMEOUT
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{base_url}/", timeout=2).ok:
                logger.info("내장 백엔드 기동 완료: %s", base_url)
                return base_url
        except requests.RequestException:
            time.sleep(0.3)
    raise RuntimeError(f"내장 백엔드가 {BOOT_TIMEOUT}초 안에 응답하지 않았습니다.")
