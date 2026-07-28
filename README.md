# 영화 리뷰 & 감성 분석 서비스

Streamlit(프론트) + FastAPI(백엔드) + KoELECTRA-small 기반 한국어 감성 분석.
리뷰 텍스트의 감성 점수 평균만으로 영화 평점을 산출합니다.
감성 분석 모델은 INT8 양자화로 **14.2MB**까지 줄여 저장소에 함께 넣었습니다(2번 절 참고).

```
backend/    FastAPI · SQLAlchemy · 감성 분석 서빙
frontend/   Streamlit 앱 (streamlit_app.py + styles.css + .streamlit/)
```

## 화면 구성

| 페이지 | 내용 |
|---|---|
| 🎬 영화 목록 | 포스터 카드 그리드, 검색(제목·감독·장르), 정렬(등록·평점·리뷰수·개봉·제목), 열 수 조절, 페이지네이션(3줄 단위), 상세 다이얼로그(리뷰 전체·리뷰 삭제), 삭제 확인 |
| ✍️ 리뷰 등록 | 영화 선택 + 미리보기 카드, 리뷰 작성, **미리 분석만**(저장 없이 감성만 확인), 결과 게이지, 해당 영화 최근 리뷰 |
| ➕ 영화 추가 | 입력과 동시에 갱신되는 카드 미리보기, 포스터 URL 도달 여부 확인 |
| 🕒 최근 리뷰 | 최근 N개(기본 10) 카드/표 전환, 감성 필터 · 영화 ID·등록일·내용·감성 결과 표시 |

상단 KPI(영화 수·리뷰 수·평균 평점·긍정 비율)는 `GET /stats`, 사이드바에는 백엔드 연결 상태·모델 정보와
저장 없이 문장을 분석해 보는 **감성 분석 체험** 패널이 있습니다.
색·간격 등 디자인 토큰은 `frontend/styles.css` 상단에서 한 번에 조정할 수 있습니다.

## 1. 백엔드 실행

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

* Swagger UI: http://localhost:8000/docs
* 감성 분석 모델(INT8 ONNX, 14.2MB)은 `backend/models/onnx-int8`에 커밋돼 있어 다운로드가
  없습니다. torch도 필요 없습니다. 모델을 못 읽으면 자동으로 규칙 기반 폴백으로 동작합니다.
* 데모 데이터(한국 영화 50편 + 각 10개씩 리뷰 500개) 등록:

```bash
python scripts/seed_data.py                 # 이미 있는 제목은 건너뛴다 (중복 등록 없음)
python scripts/seed_data.py --limit 10      # 앞에서 10편만
python scripts/seed_data.py --workers 8     # 리뷰 등록 동시 요청 수 (기본 4)
```

리뷰는 영화별 감상 포인트 + 문장 템플릿(조사 자동 처리)으로 생성하며, 긍정 6~8개 / 부정 2~4개
비율로 섞인다. 영화 메타데이터(개봉일·감독·장르·포스터)는 위키데이터/위키백과에서 수집해
감독 일치 여부와 포스터 URL 응답까지 검증한 값이다.

### 환경변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | `sqlite:///backend/movie.db` | DB 접속 URL |
| `SENTIMENT_BACKEND` | `auto` | `onnx` / `transformers` / `lexicon` / `auto` |
| `SENTIMENT_MODEL` | `daekeun-ml/koelectra-small-v3-nsmc` | HuggingFace 모델 ID |
| `ONNX_MODEL_DIR` | `backend/models/onnx-int8` | 양자화 모델 경로 |

## 2. 모델 경량화

### 모델 선정

리뷰 감성 분석은 **이진 분류 한 가지**만 하면 되므로 범용 대형 모델이 필요 없다.
후보를 NSMC(네이버 영화 리뷰) test 1,000건에서 동일 조건(CPU 1스레드)으로 직접 비교했다.

| 모델 | 파라미터 | FP32 크기 | 지연 | 정확도 |
|---|---:|---:|---:|---:|
| matthewburke/korean_sentiment (KcELECTRA-base) | 124.5M | 475.1MB | 47.5ms | 0.9020 |
| **daekeun-ml/koelectra-small-v3-nsmc** | **14.1M** | **53.9MB** | **9.2ms** | **0.8980** |
| monologg/koelectra-small-finetuned-nsmc | 13.8M | 52.5MB | 9.5ms | 0.8920 |

KoELECTRA-small-v3(hidden 256 · embedding 128)를 NSMC로 파인튜닝한 모델이 **8.8배 작고
5.2배 빠른데 정확도는 0.40%p**만 낮다. 영화 리뷰라는 도메인도 정확히 일치해 이 모델을 택했다.

### INT8 동적 양자화

```bash
pip install -r requirements-quantize.txt
python scripts/quantize_onnx.py                    # 기본 모델
python scripts/quantize_onnx.py --model <HF_ID>    # 다른 모델
```

가중치만 INT8로 미리 변환하고 활성값은 추론 시점에 스케일을 잡는 **동적 양자화**를 썼다.
보정(calibration) 데이터가 필요 없어 파이프라인이 단순하고 정확도 손실이 작다.

### 최종 결과

| 단계 | 모델 크기 | 지연 | 정확도 | 런타임 의존성 |
|---|---:|---:|---:|---|
| 원본 (KcELECTRA-base, PyTorch) | 475.1MB | 47.5ms | 0.9020 | torch 1,117MB + transformers 73MB |
| 소형 모델 교체 (FP32 ONNX) | 54.1MB | 9.2ms | 0.8980 | onnxruntime 40MB |
| **+ INT8 양자화 (배포본)** | **14.2MB** | **2.9ms** | **0.8990** | **onnxruntime 40MB + tokenizers 7MB** |

**모델 33배 · 의존성 25배 축소, 추론 16배 가속, 정확도 −0.30%p.**

추가로 토크나이저를 `transformers`(73MB) 대신 `tokenizers`(7MB)로 직접 올렸다.
`tokenizer.json`에 정규화·분절 규칙이 모두 들어 있어 결과는 동일하다(정확도 0.8990로 일치 확인).

이 결과로 모델이 GitHub에 그대로 커밋 가능한 크기가 되어, 배포 환경에서 런타임 다운로드 없이
바로 서빙된다. 모델 로딩에 실패해도 규칙 기반(lexicon) 폴백이 서비스를 이어받는다.

## 3. 프론트엔드 실행

```bash
cd frontend
pip install -r requirements.txt
API_URL=http://localhost:8000 streamlit run streamlit_app.py
```

`API_URL`을 주지 않으면 프론트엔드가 FastAPI를 같은 프로세스에 자동으로 띄웁니다
(`frontend/embedded_backend.py`). 백엔드를 따로 실행하지 않아도 앱이 그대로 동작합니다.

## 4. Streamlit Cloud 배포

Streamlit Cloud는 앱 프로세스 하나만 띄우므로, FastAPI를 uvicorn 백그라운드 스레드로 함께
기동해 별도 호스팅 없이 배포합니다. 데이터는 여전히 전부 FastAPI + SQLite가 관리하고
Streamlit은 HTTP로만 접근하므로 프론트/백엔드 분리 구조는 유지됩니다.

```
저장소 루트
├─ requirements.txt      ← Cloud가 읽는 통합 의존성 (frontend + backend)
├─ .streamlit/config.toml ← Cloud가 읽는 테마 설정 (루트에 있어야 적용됨)
├─ frontend/streamlit_app.py   ← Main file path
├─ frontend/embedded_backend.py ← FastAPI 인프로세스 기동
└─ backend/seed/movie.db  ← 데모용 시드 DB (영화 50 · 리뷰 500)
```

1. 저장소를 GitHub에 푸시합니다.
2. [share.streamlit.io](https://share.streamlit.io) → **Create app** → 저장소·브랜치 선택
3. **Main file path**: `frontend/streamlit_app.py`
4. **Advanced settings → Python version: 3.12** (권장 — 고정한 휠 버전들이 가장 안정적으로 맞습니다)
5. Deploy. 모델이 저장소에 들어 있어 런타임 다운로드가 없고, 의존성도 가벼워 1~2분이면 뜹니다.

Secrets 설정은 필요 없습니다. 백엔드를 Render/Railway 등 외부에 따로 올렸다면
그때만 App settings → Secrets 에 주소를 넣으면 내장 기동 대신 그쪽을 호출합니다.

```toml
API_URL = "https://your-backend.onrender.com"
```

### 배포 시 참고

* **DB**: 시드 DB를 임시 디렉터리로 복사해 사용합니다. 배포 후 등록한 리뷰는 앱이 재시작되면
  초기 상태로 돌아갑니다(무료 티어 파일시스템이 휘발성).
* **Swagger UI**: 백엔드가 `127.0.0.1`에만 바인딩되므로 `/docs`는 외부에 노출되지 않습니다.
  로컬에서 `uvicorn app.main:app --port 8000`으로 확인합니다.
* **메모리**: 무료 티어는 약 2.7GB인데, 경량화 덕분에 모델이 14.2MB뿐이라 여유가 충분합니다.
  모델 로딩이 실패하더라도 규칙 기반(lexicon) 폴백이 서비스를 이어받습니다.

## 5. API 요약

| Method | Path | 설명 |
|---|---|---|
| POST | `/movies` | 영화 등록 |
| GET | `/movies` | 전체 조회 (리뷰 수·평점 포함, `q` 검색 / `sort` 정렬 지원) |
| GET | `/movies/{id}` | 단일 조회 |
| PATCH | `/movies/{id}` | 부분 수정 |
| DELETE | `/movies/{id}` | 삭제 (리뷰 CASCADE) |
| GET | `/movies/{id}/rating` | 평점 조회 |
| GET | `/movies/{id}/reviews` | 영화별 리뷰 조회 |
| POST | `/reviews` | 리뷰 등록 (감성 분석 자동) |
| GET | `/reviews` | 최근 리뷰 조회 (기본 10개) |
| GET | `/reviews/{id}` | 단일 리뷰 조회 |
| DELETE | `/reviews/{id}` | 리뷰 삭제 |
| POST | `/sentiment` | 감성 분석 단독 실행 |
| GET | `/model-info` | 로딩된 모델 정보 |
| GET | `/stats` | 서비스 전체 통계 (영화 수·리뷰 수·평균 평점·긍정 비율) |

## 6. 평점 산정

`평점 = (Σ 긍정확률 / 리뷰수) × 5` — 조회 시점에 `AVG()`로 집계하며 별도 컬럼으로 저장하지 않습니다.
