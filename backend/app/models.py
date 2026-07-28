"""SQLAlchemy ORM 모델 (ERD 대응)."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Movie(Base):
    """영화 테이블."""

    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    director: Mapped[str | None] = mapped_column(String(100), nullable=True)
    genre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    poster_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    reviews: Mapped[list["Review"]] = relationship(
        back_populates="movie",
        cascade="all, delete-orphan",  # 영화 삭제 시 리뷰도 함께 삭제
        passive_deletes=True,
    )


class Review(Base):
    """리뷰 테이블. 감성 분석 결과를 함께 저장한다."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 감성 분석 결과
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)  # positive/negative
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0.0 ~ 1.0
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    movie: Mapped["Movie"] = relationship(back_populates="reviews")
