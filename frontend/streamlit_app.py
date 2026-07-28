"""영화 리뷰 & 감성 분석 - Streamlit 프론트엔드.

모든 데이터는 FastAPI 백엔드에서 관리하며, Streamlit은 조회/입력 UI만 담당한다.
(session_state는 화면 전환·선택 상태 유지용으로만 사용하고 데이터 저장에는 쓰지 않는다.)
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from html import escape
from math import ceil
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="영화 리뷰 & 감성 분석",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_DIR = Path(__file__).resolve().parent
TIMEOUT = 30

PAGE_MOVIES = "🎬 영화 목록"
PAGE_REVIEW = "✍️ 리뷰 등록"
PAGE_ADD = "➕ 영화 추가"
PAGE_RECENT = "🕒 최근 리뷰"
PAGES = [PAGE_MOVIES, PAGE_REVIEW, PAGE_ADD, PAGE_RECENT]

ROWS_PER_PAGE = 3  # 영화 목록 한 페이지에 보여줄 카드 줄 수

SORT_OPTIONS = {
    "최근 등록순": "recent",
    "평점 높은순": "rating",
    "리뷰 많은순": "reviews",
    "개봉 최신순": "release",
    "제목순": "title",
}


@st.cache_resource(show_spinner="백엔드를 준비하는 중입니다…")
def _embedded_backend_url() -> str:
    """FastAPI를 같은 프로세스에 띄우고 주소를 돌려준다(Streamlit Cloud 배포용).

    cache_resource라 스크립트가 몇 번 재실행돼도 서버는 한 번만 기동된다.
    """
    import embedded_backend  # noqa: PLC0415

    return embedded_backend.start()


def _secret_api_url() -> str | None:
    """secrets.toml에서 API_URL을 읽는다. 없으면 None.

    st.secrets는 파일이 없으면 예외를 던지기 전에 화면에 에러 박스를 그리므로,
    try/except로 막을 수 없다. 파일 존재 여부를 먼저 확인한다.
    """
    candidates = (
        Path.home() / ".streamlit" / "secrets.toml",  # Streamlit Cloud가 대시보드 값을 쓰는 위치
        Path.cwd() / ".streamlit" / "secrets.toml",
    )
    if not any(p.exists() for p in candidates):
        return None
    try:
        return st.secrets["API_URL"]
    except Exception:  # noqa: BLE001  (키가 없는 경우)
        return None


def _resolve_api_url() -> str:
    """API_URL 우선순위: 환경변수 > st.secrets > 내장 백엔드 자동 기동."""
    if os.getenv("API_URL"):
        return os.environ["API_URL"]
    if secret_url := _secret_api_url():
        return secret_url
    # 외부 백엔드 주소가 없으면(Streamlit Cloud 등) 백엔드를 직접 띄운다.
    return _embedded_backend_url()


API_URL = _resolve_api_url().rstrip("/")


# ------------------------------------------------------------------ 스타일
CSS_PATH = BASE_DIR / "styles.css"


@st.cache_data(show_spinner=False)
def _load_css(mtime: float) -> str:  # noqa: ARG001 - mtime은 캐시 무효화 키
    """styles.css를 읽어 들인다. 파일이 수정되면 mtime이 바뀌어 캐시가 갱신된다."""
    css = CSS_PATH.read_text(encoding="utf-8")
    # 들여쓰기가 남아 있으면 마크다운이 코드블록으로 오해할 수 있어 제거한다.
    return re.sub(r"^[ \t]+", "", css, flags=re.MULTILINE)


st.markdown(f"<style>{_load_css(CSS_PATH.stat().st_mtime)}</style>", unsafe_allow_html=True)


# ------------------------------------------------------------------ API 헬퍼
def api(method: str, path: str, *, silent: bool = False, **kwargs):
    """백엔드 호출. 실패 시 None을 반환하고(silent=False면) 화면에 오류를 표시한다."""
    try:
        res = requests.request(method, f"{API_URL}{path}", timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        if not silent:
            st.error(f"백엔드에 연결할 수 없습니다: {exc}")
        return None
    if not res.ok:
        if not silent:
            try:
                detail = res.json().get("detail", res.text)
            except ValueError:
                detail = res.text
            st.error(f"요청 실패 ({res.status_code}): {detail}")
        return None
    return None if res.status_code == 204 else res.json()


@st.cache_data(ttl=15, show_spinner=False)
def fetch_movies(q: str = "", sort: str = "recent") -> list[dict]:
    params: dict = {"sort": sort, "limit": 200}
    if q:
        params["q"] = q
    return api("GET", "/movies", params=params) or []


@st.cache_data(ttl=15, show_spinner=False)
def fetch_movie_reviews(movie_id: int, limit: int = 50) -> list[dict]:
    return api("GET", f"/movies/{movie_id}/reviews", params={"limit": limit}) or []


@st.cache_data(ttl=15, show_spinner=False)
def fetch_recent_reviews(limit: int = 10) -> list[dict]:
    return api("GET", "/reviews", params={"limit": limit}) or []


@st.cache_data(ttl=15, show_spinner=False)
def fetch_rating(movie_id: int) -> dict | None:
    return api("GET", f"/movies/{movie_id}/rating", silent=True)


@st.cache_data(ttl=15, show_spinner=False)
def fetch_stats() -> dict | None:
    return api("GET", "/stats", silent=True)


@st.cache_data(ttl=60, show_spinner=False)
def fetch_model_info() -> dict | None:
    return api("GET", "/model-info", silent=True)


@st.cache_data(ttl=30, show_spinner=False)
def backend_alive() -> bool:
    return api("GET", "/", silent=True) is not None


@st.cache_data(ttl=3600, show_spinner=False)
def poster_reachable(url: str) -> bool:
    """포스터 URL이 실제로 열리는지 확인 (입력 폼 미리보기용)."""
    if not url:
        return False
    try:
        res = requests.head(url, timeout=5, allow_redirects=True)
        if res.status_code >= 400:  # HEAD를 막는 서버가 있어 GET으로 재시도
            res = requests.get(url, timeout=5, stream=True)
        return res.ok
    except requests.RequestException:
        return False


def refresh() -> None:
    """백엔드 데이터가 바뀌었을 때 캐시를 비운다."""
    st.cache_data.clear()


# ------------------------------------------------------------------ 렌더 헬퍼
def render_html(markup: str) -> None:
    """여러 줄 HTML을 한 줄로 합쳐 마크다운 파서의 간섭 없이 출력한다."""
    st.markdown("".join(line.strip() for line in markup.strip().splitlines()), unsafe_allow_html=True)


def safe_url(url: str | None) -> str:
    """CSS url(...) 안에 넣어도 안전하도록 따옴표·괄호를 인코딩한다."""
    if not url:
        return ""
    cleaned = url.strip().replace("'", "%27").replace('"', "%22").replace("(", "%28").replace(")", "%29")
    return escape(cleaned, quote=True)


def stars_html(rating: float | None) -> str:
    """0~5 평점을 부분 채움이 가능한 별 5개로 렌더링한다."""
    pct = 0 if rating is None else max(0.0, min(rating, 5.0)) / 5 * 100
    return (
        '<span class="stars"><span class="bg">★★★★★</span>'
        f'<span class="fg" style="width:{pct:.1f}%">★★★★★</span></span>'
    )


def sentiment_html(label: str | None, score: float | None) -> str:
    """감성 라벨 배지. score는 긍정 확률이므로 부정이면 1-score를 신뢰도로 보여준다."""
    if not label:
        return '<span class="sent na">미분석</span>'
    positive = label == "positive"
    cls, icon, text = ("pos", "😊", "긍정") if positive else ("neg", "😞", "부정")
    if score is not None:
        confidence = score if positive else 1 - score
        text = f"{text} {confidence:.0%}"
    return f'<span class="sent {cls}">{icon} {text}</span>'


def sentiment_text(label: str | None, score: float | None) -> str:
    """표(dataframe)용 텍스트 버전."""
    if not label:
        return "미분석"
    positive = label == "positive"
    base = "😊 긍정" if positive else "😞 부정"
    if score is None:
        return base
    return f"{base} ({(score if positive else 1 - score):.0%})"


def fmt_dt(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value.replace("T", " ")[:16]


def fmt_date(value: str | None) -> str:
    return value.replace("-", ".") if value else "미상"


def section_title(text: str, count: str = "") -> None:
    count_html = f'<span class="count">{escape(count)}</span>' if count else ""
    render_html(
        f'<div class="section-title">{escape(text)}{count_html}<span class="line"></span></div>'
    )


def empty_box(icon: str, message: str) -> None:
    render_html(f'<div class="empty-box"><span class="icon">{icon}</span>{escape(message)}</div>')


def poster_div(movie: dict, badge: bool = True, radius: str = "") -> str:
    url = safe_url(movie.get("poster_url"))
    rating = movie.get("rating")
    style = f"background-image:url('{url}'), linear-gradient(150deg,#232838,#141824);" if url else ""
    if radius:
        style += f"border-radius:{radius};"
    badge_html = (
        f'<span class="badge">★ {rating:.1f}</span>' if badge and rating is not None else ""
    )
    return f'<div class="poster{"" if url else " empty"}" style="{style}">{badge_html}</div>'


def movie_card(movie: dict, clickable: bool = False) -> str:
    """영화 카드 HTML. clickable=True면 카드 전체가 클릭 영역이 된다(styles.css에서 처리)."""
    meta = " · ".join(str(v) for v in (movie.get("director"), movie.get("genre")) if v)
    rating, count = movie.get("rating"), movie.get("review_count", 0)
    if rating is not None:
        rating_row = f'<div class="card-rating">{stars_html(rating)}<b>{rating:.2f}</b></div>'
    else:
        rating_row = '<div class="card-rating"><span class="none">아직 리뷰가 없습니다</span></div>'
    chips = f'<span class="chip">리뷰 {count}개</span>'
    if movie.get("release_date"):
        chips += f'<span class="chip">{fmt_date(movie["release_date"])} 개봉</span>'
    return (
        f'<div class="movie-card{" card-click" if clickable else ""}">'
        f"{poster_div(movie)}"
        '<div class="card-body">'
        f'<div class="card-title">{escape(movie["title"])}</div>'
        f'<div class="card-meta">{escape(meta) if meta else "&nbsp;"}</div>'
        f"{rating_row}"
        f'<div class="chips">{chips}</div>'
        "</div></div>"
    )


def review_item(review: dict, movie_title: str | None = None, show_movie: bool = True) -> str:
    """리뷰 카드. show_movie=False면 영화 정보를 생략한다(이미 그 영화 화면일 때)."""
    cls = {"positive": "pos", "negative": "neg"}.get(review.get("sentiment") or "", "")
    if not show_movie:
        title_chip = ""
    elif movie_title:
        title_chip = f'<span class="mid">#{review["movie_id"]} {escape(movie_title)}</span>'
    else:
        title_chip = f'<span class="mid">영화 #{review["movie_id"]}</span>'
    return (
        f'<div class="review {cls}"><div class="head">'
        f'<span class="author">{escape(review["author"])}</span>'
        f"{title_chip}"
        f'<span class="date">{fmt_dt(review.get("created_at"))}</span>'
        '<span class="spacer"></span>'
        f'{sentiment_html(review.get("sentiment"), review.get("sentiment_score"))}'
        f'</div><div class="body">{escape(review["content"])}</div></div>'
    )


def gauge(score: float, positive: bool) -> str:
    color = (
        "linear-gradient(90deg,#10b981,#34d399)" if positive else "linear-gradient(90deg,#ef4444,#f87171)"
    )
    width = (score if positive else 1 - score) * 100
    return f'<div class="gauge"><div style="width:{width:.1f}%;background:{color}"></div></div>'


# ------------------------------------------------------------------ 상태 관리
def rerun_dialog() -> None:
    """다이얼로그를 닫지 않고 내용만 다시 그린다."""
    try:
        st.rerun(scope="fragment")
    except Exception:  # noqa: BLE001 - fragment 스코프를 지원하지 않는 버전 대비
        st.rerun()


def goto(page: str, movie_id: int | None = None) -> None:
    """다음 실행에서 페이지를 전환한다(위젯 생성 후 직접 대입이 불가하므로 예약 방식)."""
    st.session_state["pending_page"] = page
    if movie_id is not None:
        st.session_state["review_target_id"] = movie_id
    st.rerun()


if "pending_page" in st.session_state:  # 위젯 생성 전에 적용해야 한다
    st.session_state["nav_page"] = st.session_state.pop("pending_page")
st.session_state.setdefault("nav_page", PAGE_MOVIES)


# ------------------------------------------------------------------ 다이얼로그
@st.dialog("영화 상세", width="large")
def movie_detail_dialog(movie: dict) -> None:
    left, right = st.columns([1, 1.7], gap="medium")
    with left:
        render_html(f'<div class="movie-card">{poster_div(movie, badge=False)}</div>')
    with right:
        meta = " · ".join(str(v) for v in (movie.get("director"), movie.get("genre")) if v)
        rating = movie.get("rating")
        stat = fetch_rating(movie["id"]) or {}
        rating_block = (
            f'<div class="card-rating">{stars_html(rating)}<b>{rating:.2f}</b>'
            '<span class="none">/ 5.0</span></div>'
            if rating is not None
            else '<div class="card-rating"><span class="none">아직 리뷰가 없습니다</span></div>'
        )
        positive_ratio = stat.get("positive_ratio")
        chips = f'<span class="chip">리뷰 {movie.get("review_count", 0)}개</span>'
        if positive_ratio is not None:
            chips += f'<span class="chip pos">긍정 {positive_ratio:.0%}</span>'
            chips += f'<span class="chip neg">부정 {1 - positive_ratio:.0%}</span>'
        render_html(
            f'<div class="hero"><div class="eyebrow">MOVIE #{movie["id"]}</div>'
            f'<h1 style="font-size:1.7rem">{escape(movie["title"])}</h1>'
            f'<p>{escape(meta) if meta else "정보 없음"} · {fmt_date(movie.get("release_date"))} 개봉</p>'
            f"</div>{rating_block}"
            f'<div class="chips">{chips}</div>'
        )
        st.write("")
        write_col, delete_col = st.columns([3, 1])
        if write_col.button("✍️ 이 영화에 리뷰 쓰기", key="detail-write", type="primary",
                            use_container_width=True):
            goto(PAGE_REVIEW, movie["id"])
        if delete_col.button("🗑 삭제", key="detail-delete", use_container_width=True):
            st.session_state["confirm_delete"] = movie["id"]
            rerun_dialog()

    if st.session_state.get("confirm_delete") == movie["id"]:
        st.warning(
            f"**{movie['title']}** 을(를) 삭제하면 이 영화에 달린 리뷰 "
            f"{movie.get('review_count', 0)}개도 함께 삭제됩니다. 되돌릴 수 없습니다.",
            icon="⚠️",
        )
        cancel_col, confirm_col, _ = st.columns([1, 1, 3])
        if cancel_col.button("취소", key="del-cancel", use_container_width=True):
            st.session_state.pop("confirm_delete", None)
            rerun_dialog()
        if confirm_col.button("삭제", key="del-confirm", type="primary", use_container_width=True):
            api("DELETE", f"/movies/{movie['id']}")
            refresh()
            st.session_state.pop("confirm_delete", None)
            st.session_state["flash"] = f"'{movie['title']}' 을(를) 삭제했습니다."
            st.rerun()  # 목록까지 갱신해야 하므로 다이얼로그를 닫는다

    st.write("")
    reviews = fetch_movie_reviews(movie["id"], limit=50)
    section_title("리뷰", f"{len(reviews)}개")
    if not reviews:
        empty_box("💬", "아직 등록된 리뷰가 없습니다.")
        return
    for review in reviews:
        col_body, col_del = st.columns([12, 1])
        with col_body:
            render_html(review_item(review, show_movie=False))
        if col_del.button("🗑", key=f"rv-del-{review['id']}", help="이 리뷰 삭제"):
            api("DELETE", f"/reviews/{review['id']}")
            refresh()
            rerun_dialog()


# ------------------------------------------------------------------ 사이드바
with st.sidebar:
    render_html(
        '<div class="side-brand"><div class="logo">🎬</div>'
        '<div><div class="name">Movie Review</div>'
        '<div class="sub">SENTIMENT ANALYSIS</div></div></div>'
    )
    alive = backend_alive()
    info = fetch_model_info() if alive else None
    render_html(
        '<div class="side-box">'
        f'<div class="row"><span class="k">백엔드</span><span class="v">'
        f'<span class="status {"ok" if alive else "ng"}"><span class="dot"></span>'
        f'{"연결됨" if alive else "연결 실패"}</span></span></div>'
        f'<div class="row"><span class="k">주소</span><span class="v">{escape(API_URL)}</span></div>'
        f'<div class="row"><span class="k">모델</span><span class="v">'
        f'{escape(info["model"]) if info else "-"}</span></div>'
        f'<div class="row"><span class="k">추론 백엔드</span><span class="v">'
        f'{escape(info["backend"]) if info else "-"}</span></div>'
        "</div>"
    )
    if not alive:
        st.error("백엔드가 실행 중인지 확인해 주세요.\n\n`uvicorn app.main:app --reload`")

    if st.button("🔄 새로고침", use_container_width=True):
        refresh()
        st.rerun()
    st.link_button("📖 API 문서 (Swagger)", f"{API_URL}/docs", use_container_width=True)

    with st.expander("🧪 감성 분석 체험"):
        st.caption("저장 없이 문장만 분석해 봅니다.")
        sample = st.text_area(
            "문장", placeholder="연출이 정말 훌륭했어요", height=80, label_visibility="collapsed"
        )
        if st.button("분석하기", use_container_width=True, disabled=not sample.strip()):
            with st.spinner("분석 중..."):
                result = api("POST", "/sentiment", json={"text": sample.strip()})
            if result:
                render_html(sentiment_html(result["label"], result["score"]))
                render_html(gauge(result["score"], result["label"] == "positive"))


# ------------------------------------------------------------------ 헤더
render_html(
    '<div class="hero"><div class="eyebrow">Korean Sentiment · FastAPI × Streamlit</div>'
    "<h1>영화 리뷰 &amp; 감성 분석</h1>"
    "<p>리뷰를 등록하면 한국어 감성 분석 모델이 자동으로 평가하고, "
    "그 점수를 5점 척도 평점으로 환산해 보여줍니다.</p></div>"
)

stats = fetch_stats()
if stats:
    avg = f'{stats["avg_rating"]:.2f}<small>/ 5.0</small>' if stats.get("avg_rating") else "-"
    ratio = f'{stats["positive_ratio"]:.0%}' if stats.get("positive_ratio") is not None else "-"
    render_html(
        '<div class="kpi-row">'
        f'<div class="kpi"><div class="label">등록 영화</div><div class="value">{stats["movie_count"]}<small>편</small></div></div>'
        f'<div class="kpi"><div class="label">등록 리뷰</div><div class="value">{stats["review_count"]}<small>개</small></div></div>'
        f'<div class="kpi"><div class="label">평균 평점</div><div class="value">{avg}</div></div>'
        f'<div class="kpi"><div class="label">긍정 리뷰 비율</div><div class="value">{ratio}</div></div>'
        "</div>"
    )

st.write("")
page = st.radio("페이지", PAGES, key="nav_page", horizontal=True, label_visibility="collapsed")

if flash := st.session_state.pop("flash", None):
    st.success(flash, icon="✅")


# ------------------------------------------------------------------ 영화 목록
def page_movies() -> None:
    col_q, col_sort, col_cols = st.columns([3, 1.4, 1.1])
    query = col_q.text_input(
        "검색", placeholder="🔍 제목 · 감독 · 장르로 검색", label_visibility="collapsed"
    )
    sort_label = col_sort.selectbox("정렬", list(SORT_OPTIONS), label_visibility="collapsed")
    per_row = col_cols.selectbox("한 줄에", [3, 4, 5], index=1, format_func=lambda n: f"{n}열 보기",
                                 label_visibility="collapsed")

    movies = fetch_movies(query.strip(), SORT_OPTIONS[sort_label])
    if not movies:
        if query.strip():
            empty_box("🔍", f"'{query.strip()}' 검색 결과가 없습니다.")
        else:
            empty_box("🎞", "등록된 영화가 없습니다. '영화 추가'에서 첫 영화를 등록해 보세요.")
        return

    # 검색어·정렬·열 수가 바뀌면 1페이지부터 다시 본다
    view_key = f"{query.strip()}|{sort_label}|{per_row}"
    if st.session_state.get("movie_view_key") != view_key:
        st.session_state["movie_view_key"] = view_key
        st.session_state["movie_page"] = 1

    per_page = per_row * ROWS_PER_PAGE
    total_pages = max(1, ceil(len(movies) / per_page))
    current = min(st.session_state.get("movie_page", 1), total_pages)
    shown = movies[(current - 1) * per_page : current * per_page]

    count = f"총 {len(movies)}편"
    if total_pages > 1:
        count += f" · {current}/{total_pages} 페이지"
    count += " · 카드를 누르면 상세·리뷰"
    section_title("영화 목록", count)

    for row_start in range(0, len(shown), per_row):
        row = shown[row_start : row_start + per_row]
        columns = st.columns(per_row, gap="medium")
        for column, movie in zip(columns, row):
            with column:
                # 카드 위에 투명 버튼을 겹쳐(styles.css) 카드 아무 곳이나 누르면 상세가 열린다.
                render_html(movie_card(movie, clickable=True))
                if st.button(f"{movie['title']} 상세 · 리뷰 보기", key=f"detail-{movie['id']}",
                             use_container_width=True):
                    movie_detail_dialog(movie)

    if total_pages > 1:
        st.write("")
        prev_col, info_col, next_col = st.columns([1, 3, 1])
        if prev_col.button("← 이전", use_container_width=True, disabled=current == 1):
            st.session_state["movie_page"] = current - 1
            st.rerun()
        info_col.markdown(
            f"<div style='text-align:center;color:#98a1b3;font-size:.85rem;padding-top:.45rem'>"
            f"{(current - 1) * per_page + 1}–{(current - 1) * per_page + len(shown)} / {len(movies)}편"
            "</div>",
            unsafe_allow_html=True,
        )
        if next_col.button("다음 →", use_container_width=True, disabled=current == total_pages):
            st.session_state["movie_page"] = current + 1
            st.rerun()


# ------------------------------------------------------------------ 리뷰 등록
def page_review() -> None:
    movies = fetch_movies()
    if not movies:
        empty_box("🎞", "먼저 영화를 등록해 주세요.")
        return

    ids = [m["id"] for m in movies]
    # '이 영화에 리뷰 쓰기'로 넘어온 경우 선택값을 미리 지정한다(위젯 생성 전이라 대입 가능).
    target_id = st.session_state.pop("review_target_id", None)
    if target_id in ids:
        st.session_state["review_movie"] = target_id
    if st.session_state.get("review_movie") not in ids:
        st.session_state["review_movie"] = ids[0]

    left, right = st.columns([1, 2], gap="large")
    with left:
        selected_id = st.selectbox(
            "영화 선택 *",
            ids,
            key="review_movie",
            format_func=lambda mid: next(m["title"] for m in movies if m["id"] == mid),
        )
        movie = next(m for m in movies if m["id"] == selected_id)
        render_html(movie_card(movie))

    with right:
        # 등록에 성공했을 때만 입력값을 비우기 위해 위젯 key에 nonce를 붙인다.
        # (미리 분석만 눌렀을 때는 작성 중인 내용이 그대로 남는다.)
        nonce = st.session_state.setdefault("review_form_nonce", 0)
        with st.form(f"add_review-{nonce}"):
            st.markdown("##### ✍️ 리뷰 작성")
            author = st.text_input(
                "작성자 이름 *", placeholder="홍길동", max_chars=50, key=f"rv-author-{nonce}"
            )
            content = st.text_area(
                "리뷰 내용 *",
                height=170,
                placeholder="영화를 보고 느낀 점을 자유롭게 적어주세요.",
                key=f"rv-content-{nonce}",
            )
            st.caption("등록 즉시 한국어 감성 분석 모델이 리뷰를 평가하고 평점에 반영합니다.")
            submit_col, preview_col = st.columns([2, 1])
            submitted = submit_col.form_submit_button(
                "등록하고 감성 분석", type="primary", use_container_width=True
            )
            previewed = preview_col.form_submit_button("미리 분석만", use_container_width=True)

        saved = st.session_state.pop("review_result", None)
        if saved:
            st.success(f"'{saved['title']}'에 리뷰가 등록되었습니다.", icon="✅")
            show_sentiment_result(saved["label"], saved["score"])
        elif (submitted or previewed) and not content.strip():
            st.warning("리뷰 내용을 입력해 주세요.")
        elif previewed:
            with st.spinner("감성 분석 중..."):
                result = api("POST", "/sentiment", json={"text": content.strip()})
            if result:
                st.caption("저장되지 않은 미리보기 결과입니다.")
                show_sentiment_result(result["label"], result["score"])
        elif submitted:
            if not author.strip():
                st.warning("작성자 이름을 입력해 주세요.")
            else:
                with st.spinner("리뷰 저장 및 감성 분석 중..."):
                    review = api(
                        "POST",
                        "/reviews",
                        json={
                            "movie_id": selected_id,
                            "author": author.strip(),
                            "content": content.strip(),
                        },
                    )
                if review:
                    refresh()
                    st.session_state["review_result"] = {
                        "label": review["sentiment"],
                        "score": review["sentiment_score"],
                        "title": movie["title"],
                    }
                    st.session_state["review_form_nonce"] = nonce + 1
                    st.rerun()

    st.write("")
    reviews = fetch_movie_reviews(selected_id, limit=5)
    section_title(f"'{movie['title']}'의 최근 리뷰", f"{movie.get('review_count', 0)}개 중 {len(reviews)}개")
    if not reviews:
        empty_box("💬", "첫 번째 리뷰를 남겨보세요.")
    else:
        for review in reviews:
            render_html(review_item(review, show_movie=False))


def show_sentiment_result(label: str, score: float) -> None:
    """감성 분석 결과 패널 (등록 후 / 미리보기 공용)."""
    positive = label == "positive"
    confidence = score if positive else 1 - score
    render_html(
        f'<div class="result-panel {"pos" if positive else "neg"}">'
        f'<div class="big">{"😊 긍정 리뷰" if positive else "😞 부정 리뷰"}</div>'
        f'<div class="sub">모델 확신도 {confidence:.1%} · 긍정 확률 {score:.1%} · '
        f"평점 환산 {score * 5:.2f} / 5.0</div>"
        f'<div class="gauge-label"><span>부정</span><span>긍정</span></div>'
        f"{gauge(score, positive)}</div>"
    )


# ------------------------------------------------------------------ 영화 추가
def page_add_movie() -> None:
    nonce = st.session_state.setdefault("add_form_nonce", 0)
    left, right = st.columns([2, 1], gap="large")

    with left:
        st.markdown("##### ➕ 새 영화 등록")
        col1, col2 = st.columns(2)
        title = col1.text_input("제목 *", placeholder="기생충", key=f"add-title-{nonce}", max_chars=200)
        release = col2.date_input(
            "개봉일",
            value=date(2019, 5, 30),
            min_value=date(1900, 1, 1),
            max_value=date(2100, 12, 31),
            key=f"add-date-{nonce}",
            format="YYYY-MM-DD",
        )
        director = col1.text_input("감독", placeholder="봉준호", key=f"add-director-{nonce}", max_chars=100)
        genre = col2.text_input("장르", placeholder="드라마, 스릴러", key=f"add-genre-{nonce}", max_chars=100)
        poster_url = st.text_input(
            "포스터 URL",
            placeholder="https://upload.wikimedia.org/...",
            key=f"add-poster-{nonce}",
            help="나무위키·위키백과 등의 이미지 주소를 붙여넣으면 오른쪽에 미리보기가 표시됩니다.",
        )

        if st.button("등록하기", type="primary", use_container_width=True):
            if not title.strip():
                st.warning("제목은 필수입니다.")
            else:
                created = api(
                    "POST",
                    "/movies",
                    json={
                        "title": title.strip(),
                        "release_date": release.isoformat() if release else None,
                        "director": director.strip() or None,
                        "genre": genre.strip() or None,
                        "poster_url": poster_url.strip() or None,
                    },
                )
                if created:
                    refresh()
                    st.session_state["add_form_nonce"] = nonce + 1
                    st.session_state["flash"] = f"'{created['title']}' 등록 완료 (ID: {created['id']})"
                    st.rerun()

    with right:
        st.markdown("##### 미리보기")
        poster_ok = poster_reachable(poster_url.strip())
        preview = {
            "title": title.strip() or "제목 없음",
            "director": director.strip(),
            "genre": genre.strip(),
            "release_date": release.isoformat() if release else None,
            # 열리지 않는 주소는 미리보기에서 빈 포스터로 보여준다.
            "poster_url": poster_url.strip() if poster_ok else None,
            "review_count": 0,
            "rating": None,
        }
        render_html(movie_card(preview))
        if poster_url.strip() and not poster_ok:
            st.caption("⚠️ 포스터 주소를 불러오지 못했습니다. 이미지 파일의 직접 주소인지 확인해 주세요.")


# ------------------------------------------------------------------ 최근 리뷰
def page_recent() -> None:
    col_n, col_filter, col_view = st.columns([1, 2, 1.2])
    limit = col_n.number_input("개수", min_value=5, max_value=50, value=10, step=5,
                               label_visibility="collapsed")
    sentiment_filter = col_filter.radio(
        "감성", ["전체", "😊 긍정", "😞 부정"], horizontal=True, label_visibility="collapsed"
    )
    as_table = col_view.toggle("표로 보기")

    reviews = fetch_recent_reviews(int(limit))
    if sentiment_filter != "전체":
        wanted = "positive" if "긍정" in sentiment_filter else "negative"
        reviews = [r for r in reviews if r.get("sentiment") == wanted]

    if not reviews:
        empty_box("💬", "표시할 리뷰가 없습니다.")
        return

    titles = {m["id"]: m["title"] for m in fetch_movies()}
    section_title(f"최근 리뷰 {int(limit)}개", f"{len(reviews)}개 표시")

    if as_table:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "영화 ID": r["movie_id"],
                        "영화": titles.get(r["movie_id"], "-"),
                        "작성자": r["author"],
                        "등록일": fmt_dt(r.get("created_at")),
                        "리뷰 내용": r["content"],
                        "감성 분석 결과": sentiment_text(r.get("sentiment"), r.get("sentiment_score")),
                    }
                    for r in reviews
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        return

    for review in reviews:
        render_html(review_item(review, titles.get(review["movie_id"])))


# ------------------------------------------------------------------ 라우팅
if page == PAGE_MOVIES:
    page_movies()
elif page == PAGE_REVIEW:
    page_review()
elif page == PAGE_ADD:
    page_add_movie()
else:
    page_recent()
