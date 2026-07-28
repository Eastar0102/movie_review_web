"""DB 접근 계층 (라우터에서 ORM 쿼리를 분리)."""

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app import models, schemas


# ---------- Movie ----------
def create_movie(db: Session, data: schemas.MovieCreate) -> models.Movie:
    movie = models.Movie(**data.model_dump())
    db.add(movie)
    db.commit()
    db.refresh(movie)
    return movie


def get_movie(db: Session, movie_id: int) -> models.Movie | None:
    return db.get(models.Movie, movie_id)


def list_movies(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    q: str | None = None,
    sort: str = "recent",
) -> list[models.Movie]:
    """영화 목록 조회. q로 제목/감독/장르 검색, sort로 정렬 방식을 지정한다."""
    stmt = select(models.Movie)

    if q:
        keyword = f"%{q.strip()}%"
        stmt = stmt.where(
            models.Movie.title.ilike(keyword)
            | models.Movie.director.ilike(keyword)
            | models.Movie.genre.ilike(keyword)
        )

    if sort in {"rating", "reviews"}:
        # 평점/리뷰 수 정렬은 리뷰 집계가 필요하므로 서브쿼리를 조인한다.
        agg = (
            select(
                models.Review.movie_id.label("movie_id"),
                func.count(models.Review.id).label("cnt"),
                func.avg(models.Review.sentiment_score).label("avg_score"),
            )
            .group_by(models.Review.movie_id)
            .subquery()
        )
        column = agg.c.avg_score if sort == "rating" else agg.c.cnt
        stmt = stmt.outerjoin(agg, agg.c.movie_id == models.Movie.id).order_by(
            desc(func.coalesce(column, 0)), desc(models.Movie.id)
        )
    elif sort == "title":
        stmt = stmt.order_by(models.Movie.title.asc())
    elif sort == "release":
        stmt = stmt.order_by(desc(models.Movie.release_date), desc(models.Movie.id))
    else:  # recent — 최근 등록순
        stmt = stmt.order_by(desc(models.Movie.id))

    return list(db.scalars(stmt.offset(skip).limit(limit)))


def update_movie(db: Session, movie: models.Movie, data: schemas.MovieUpdate) -> models.Movie:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(movie, field, value)
    db.commit()
    db.refresh(movie)
    return movie


def delete_movie(db: Session, movie: models.Movie) -> None:
    db.delete(movie)
    db.commit()


# ---------- Review ----------
def create_review(
    db: Session,
    data: schemas.ReviewCreate,
    sentiment: str | None,
    sentiment_score: float | None,
) -> models.Review:
    review = models.Review(
        movie_id=data.movie_id,
        author=data.author,
        content=data.content,
        sentiment=sentiment,
        sentiment_score=sentiment_score,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def get_review(db: Session, review_id: int) -> models.Review | None:
    return db.get(models.Review, review_id)


def list_reviews(
    db: Session, movie_id: int | None = None, skip: int = 0, limit: int = 10
) -> list[models.Review]:
    stmt = select(models.Review)
    if movie_id is not None:
        stmt = stmt.where(models.Review.movie_id == movie_id)
    stmt = stmt.order_by(desc(models.Review.created_at), desc(models.Review.id))
    stmt = stmt.offset(skip).limit(limit)
    return list(db.scalars(stmt))


def delete_review(db: Session, review: models.Review) -> None:
    db.delete(review)
    db.commit()


# ---------- 집계 ----------
def get_rating_stats(db: Session, movie_id: int) -> dict:
    """감성 점수 평균 기반 평점 통계."""
    row = db.execute(
        select(
            func.count(models.Review.id),
            func.avg(models.Review.sentiment_score),
        ).where(models.Review.movie_id == movie_id)
    ).one()
    count, avg_score = row[0], row[1]

    positive = db.scalar(
        select(func.count(models.Review.id)).where(
            models.Review.movie_id == movie_id,
            models.Review.sentiment == "positive",
        )
    )

    return {
        "movie_id": movie_id,
        "review_count": count or 0,
        "avg_sentiment_score": round(avg_score, 4) if avg_score is not None else None,
        # 0.0~1.0 감성 점수를 5점 척도로 환산
        "rating": round(avg_score * 5, 2) if avg_score is not None else None,
        "positive_ratio": round(positive / count, 4) if count else None,
    }


def get_service_stats(db: Session) -> dict:
    """서비스 전체 집계 (영화 수 / 리뷰 수 / 평균 평점 / 긍정 비율)."""
    movie_count = db.scalar(select(func.count(models.Movie.id))) or 0
    review_count, avg_score = db.execute(
        select(func.count(models.Review.id), func.avg(models.Review.sentiment_score))
    ).one()
    positive = db.scalar(
        select(func.count(models.Review.id)).where(models.Review.sentiment == "positive")
    )
    return {
        "movie_count": movie_count,
        "review_count": review_count or 0,
        "avg_rating": round(avg_score * 5, 2) if avg_score is not None else None,
        "positive_ratio": round(positive / review_count, 4) if review_count else None,
    }


def get_stats_map(db: Session, movie_ids: list[int]) -> dict[int, dict]:
    """여러 영화의 리뷰 수/평점을 한 번에 조회 (N+1 방지)."""
    if not movie_ids:
        return {}
    rows = db.execute(
        select(
            models.Review.movie_id,
            func.count(models.Review.id),
            func.avg(models.Review.sentiment_score),
        )
        .where(models.Review.movie_id.in_(movie_ids))
        .group_by(models.Review.movie_id)
    ).all()
    return {
        mid: {
            "review_count": cnt,
            "rating": round(avg * 5, 2) if avg is not None else None,
        }
        for mid, cnt, avg in rows
    }
