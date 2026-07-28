"""영화 관리 API."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db

router = APIRouter(prefix="/movies", tags=["movies"])


def _to_out(movie, stats: dict | None = None) -> schemas.MovieOut:
    stats = stats or {}
    out = schemas.MovieOut.model_validate(movie)
    out.review_count = stats.get("review_count", 0)
    out.rating = stats.get("rating")
    return out


@router.post(
    "",
    response_model=schemas.MovieOut,
    status_code=status.HTTP_201_CREATED,
    summary="영화 등록",
    description="제목, 개봉일, 감독, 장르, 포스터 URL을 받아 새 영화를 등록한다.",
)
def create_movie(payload: schemas.MovieCreate, db: Session = Depends(get_db)):
    return _to_out(crud.create_movie(db, payload))


@router.get(
    "",
    response_model=list[schemas.MovieOut],
    summary="전체 영화 조회",
    description=(
        "등록된 영화를 조회한다. 검색어(q)로 제목·감독·장르를 필터링하고 sort로 정렬 방식을 지정할 수 있다. "
        "각 영화의 리뷰 수와 평균 평점(5점 척도)을 함께 반환한다."
    ),
)
def list_movies(
    skip: int = Query(0, ge=0, description="건너뛸 개수"),
    limit: int = Query(100, ge=1, le=200, description="가져올 최대 개수"),
    q: str | None = Query(None, description="제목·감독·장르 검색어"),
    sort: str = Query(
        "recent",
        pattern="^(recent|title|release|rating|reviews)$",
        description="정렬 방식: recent(등록순) | title(제목순) | release(개봉순) | rating(평점순) | reviews(리뷰많은순)",
    ),
    db: Session = Depends(get_db),
):
    movies = crud.list_movies(db, skip=skip, limit=limit, q=q, sort=sort)
    stats = crud.get_stats_map(db, [m.id for m in movies])
    return [_to_out(m, stats.get(m.id)) for m in movies]


@router.get(
    "/{movie_id}",
    response_model=schemas.MovieOut,
    summary="특정 영화 조회",
    description="영화 ID로 단일 영화의 상세 정보를 조회한다.",
)
def get_movie(movie_id: int, db: Session = Depends(get_db)):
    movie = crud.get_movie(db, movie_id)
    if movie is None:
        raise HTTPException(status_code=404, detail=f"영화 {movie_id}를 찾을 수 없습니다.")
    stats = crud.get_stats_map(db, [movie_id])
    return _to_out(movie, stats.get(movie_id))


@router.patch(
    "/{movie_id}",
    response_model=schemas.MovieOut,
    summary="영화 정보 수정",
    description="전달된 필드만 부분 수정한다.",
)
def update_movie(movie_id: int, payload: schemas.MovieUpdate, db: Session = Depends(get_db)):
    movie = crud.get_movie(db, movie_id)
    if movie is None:
        raise HTTPException(status_code=404, detail=f"영화 {movie_id}를 찾을 수 없습니다.")
    return _to_out(crud.update_movie(db, movie, payload))


@router.delete(
    "/{movie_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="특정 영화 삭제",
    description="영화를 삭제한다. 해당 영화에 달린 리뷰도 함께 삭제된다(CASCADE).",
)
def delete_movie(movie_id: int, db: Session = Depends(get_db)):
    movie = crud.get_movie(db, movie_id)
    if movie is None:
        raise HTTPException(status_code=404, detail=f"영화 {movie_id}를 찾을 수 없습니다.")
    crud.delete_movie(db, movie)


@router.get(
    "/{movie_id}/rating",
    response_model=schemas.RatingOut,
    summary="영화 평점 조회",
    description="해당 영화 리뷰들의 감성 분석 점수 평균과 이를 5점 척도로 환산한 평점, 긍정 비율을 반환한다.",
)
def get_rating(movie_id: int, db: Session = Depends(get_db)):
    if crud.get_movie(db, movie_id) is None:
        raise HTTPException(status_code=404, detail=f"영화 {movie_id}를 찾을 수 없습니다.")
    return crud.get_rating_stats(db, movie_id)


@router.get(
    "/{movie_id}/reviews",
    response_model=list[schemas.ReviewOut],
    summary="특정 영화의 리뷰 조회",
    description="해당 영화에 달린 리뷰를 최신순으로 조회한다.",
)
def get_movie_reviews(
    movie_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if crud.get_movie(db, movie_id) is None:
        raise HTTPException(status_code=404, detail=f"영화 {movie_id}를 찾을 수 없습니다.")
    return crud.list_reviews(db, movie_id=movie_id, skip=skip, limit=limit)
