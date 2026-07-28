"""Pydantic 요청/응답 스키마."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------- Movie ----------
class MovieCreate(BaseModel):
    title: str = Field(..., max_length=200, description="영화 제목", examples=["기생충"])
    release_date: date | None = Field(None, description="개봉일 (YYYY-MM-DD)", examples=["2019-05-30"])
    director: str | None = Field(None, max_length=100, description="감독", examples=["봉준호"])
    genre: str | None = Field(None, max_length=100, description="장르", examples=["드라마"])
    poster_url: str | None = Field(None, description="포스터 이미지 URL")


class MovieUpdate(BaseModel):
    title: str | None = None
    release_date: date | None = None
    director: str | None = None
    genre: str | None = None
    poster_url: str | None = None


class MovieOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    release_date: date | None
    director: str | None
    genre: str | None
    poster_url: str | None
    created_at: datetime
    review_count: int = Field(0, description="등록된 리뷰 수")
    rating: float | None = Field(
        None, description="감성 분석 점수 평균을 5점 척도로 환산한 평균 평점"
    )


# ---------- Review ----------
class ReviewCreate(BaseModel):
    movie_id: int = Field(..., description="리뷰 대상 영화 ID", examples=[1])
    author: str = Field(..., max_length=50, description="작성자 이름", examples=["홍길동"])
    content: str = Field(..., min_length=1, description="리뷰 내용", examples=["연출이 정말 훌륭했어요."])


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    movie_id: int
    author: str
    content: str
    sentiment: str | None = Field(None, description="감성 분석 라벨 (positive / negative)")
    sentiment_score: float | None = Field(None, description="긍정 확률 (0.0 ~ 1.0)")
    created_at: datetime


# ---------- Sentiment ----------
class SentimentRequest(BaseModel):
    text: str = Field(..., min_length=1, description="분석할 문장", examples=["배우들 연기가 최고였다"])


class SentimentResult(BaseModel):
    label: str = Field(..., description="positive / negative")
    score: float = Field(..., description="긍정 확률 (0.0 ~ 1.0)")
    model: str = Field(..., description="추론에 사용된 모델/백엔드 이름")


# ---------- Rating ----------
class RatingOut(BaseModel):
    movie_id: int
    review_count: int
    avg_sentiment_score: float | None = Field(None, description="감성 점수 평균 (0.0 ~ 1.0)")
    rating: float | None = Field(None, description="5점 척도 환산 평점")
    positive_ratio: float | None = Field(None, description="긍정 리뷰 비율")


# ---------- Stats ----------
class ServiceStats(BaseModel):
    movie_count: int = Field(..., description="등록된 영화 수")
    review_count: int = Field(..., description="등록된 리뷰 수")
    avg_rating: float | None = Field(None, description="전체 평균 평점 (5점 척도)")
    positive_ratio: float | None = Field(None, description="전체 긍정 리뷰 비율")
