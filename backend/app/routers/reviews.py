"""리뷰 관리 및 감성 분석 API."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db
from app.sentiment import analyzer

router = APIRouter(tags=["reviews"])


@router.post(
    "/reviews",
    response_model=schemas.ReviewOut,
    status_code=status.HTTP_201_CREATED,
    summary="리뷰 등록 (감성 분석 자동 실행)",
    description=(
        "리뷰를 저장하면서 내용에 대한 감성 분석을 자동으로 수행하고, "
        "결과 라벨(positive/negative)과 긍정 확률을 함께 저장·반환한다."
    ),
)
def create_review(payload: schemas.ReviewCreate, db: Session = Depends(get_db)):
    if crud.get_movie(db, payload.movie_id) is None:
        raise HTTPException(status_code=404, detail=f"영화 {payload.movie_id}를 찾을 수 없습니다.")
    result = analyzer.predict(payload.content)
    return crud.create_review(db, payload, result["label"], result["score"])


@router.get(
    "/reviews",
    response_model=list[schemas.ReviewOut],
    summary="전체 리뷰 조회",
    description="최신순으로 리뷰를 조회한다. movie_id를 주면 특정 영화의 리뷰만 필터링한다. 기본 10개.",
)
def list_reviews(
    movie_id: int | None = Query(None, description="특정 영화로 필터링"),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100, description="최대 개수 (기본 10)"),
    db: Session = Depends(get_db),
):
    return crud.list_reviews(db, movie_id=movie_id, skip=skip, limit=limit)


@router.get(
    "/reviews/{review_id}",
    response_model=schemas.ReviewOut,
    summary="특정 리뷰 조회",
    description="리뷰 ID로 단일 리뷰를 조회한다.",
)
def get_review(review_id: int, db: Session = Depends(get_db)):
    review = crud.get_review(db, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"리뷰 {review_id}를 찾을 수 없습니다.")
    return review


@router.delete(
    "/reviews/{review_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="리뷰 삭제",
    description="리뷰 ID로 리뷰를 삭제한다.",
)
def delete_review(review_id: int, db: Session = Depends(get_db)):
    review = crud.get_review(db, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"리뷰 {review_id}를 찾을 수 없습니다.")
    crud.delete_review(db, review)


@router.post(
    "/sentiment",
    response_model=schemas.SentimentResult,
    summary="감성 분석 단독 실행",
    description="DB에 저장하지 않고 임의의 문장에 대해 감성 분석만 수행한다. 모델 동작 확인용.",
)
def analyze_sentiment(payload: schemas.SentimentRequest):
    return analyzer.predict(payload.text)
