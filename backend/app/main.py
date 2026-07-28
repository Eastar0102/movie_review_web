"""FastAPI 애플리케이션 진입점."""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db, init_db
from app.routers import movies, reviews
from app.sentiment import analyzer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DESCRIPTION = """
영화 정보와 사용자 리뷰를 관리하고, 리뷰에 대한 **한국어 감성 분석**을 제공하는 API입니다.

### 구성
* **movies** — 영화 등록 / 전체·단일 조회 / 수정 / 삭제 / 평점 조회
* **reviews** — 리뷰 등록(감성 분석 자동 실행) / 조회 / 삭제
* **sentiment** — 임의 문장에 대한 감성 분석 단독 실행

### 평점 산정 방식
리뷰마다 저장된 감성 분석 긍정 확률(0.0~1.0)의 평균을 구한 뒤 5를 곱해 5점 척도로 환산합니다.
"""

TAGS_METADATA = [
    {"name": "movies", "description": "영화 CRUD 및 평점 집계"},
    {"name": "reviews", "description": "리뷰 CRUD 및 감성 분석"},
    {"name": "system", "description": "헬스체크 및 모델 정보"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logging.info("DB 초기화 완료")
    yield


app = FastAPI(
    title="Movie Review & Sentiment API",
    description=DESCRIPTION,
    version="1.0.0",
    openapi_tags=TAGS_METADATA,
    lifespan=lifespan,
)

# Streamlit 프론트엔드에서의 호출 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(movies.router)
app.include_router(reviews.router)


@app.get("/", tags=["system"], summary="헬스체크", description="서버 동작 여부를 확인한다.")
def health():
    return {"status": "ok", "service": "movie-review-api"}


@app.get(
    "/model-info",
    tags=["system"],
    summary="감성 분석 모델 정보",
    description="현재 로딩된 감성 분석 백엔드(onnx / transformers / lexicon)와 모델명을 반환한다.",
)
def model_info():
    return analyzer.info


@app.get(
    "/stats",
    response_model=schemas.ServiceStats,
    tags=["system"],
    summary="서비스 전체 통계",
    description="등록된 영화 수, 리뷰 수, 전체 평균 평점(5점 척도), 긍정 리뷰 비율을 반환한다.",
)
def service_stats(db: Session = Depends(get_db)):
    return crud.get_service_stats(db)
