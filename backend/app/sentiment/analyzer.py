"""한국어 리뷰 감성 분석 모듈.

백엔드 우선순위
    1) onnx        : 동적 양자화(INT8)된 ONNX 모델 — 배포 기본값. torch 없이 동작
    2) transformers: 원본 PyTorch 체크포인트 — 양자화 전 정확도를 확인할 때 사용
    3) lexicon     : 사전 기반 규칙 폴백 — 의존성 0, 모델 로딩 실패 시에도 서비스 지속

환경변수
    SENTIMENT_BACKEND : auto(기본) | onnx | transformers | lexicon
    SENTIMENT_MODEL   : HuggingFace 모델 ID (기본 daekeun-ml/koelectra-small-v3-nsmc)
    ONNX_MODEL_DIR    : 양자화 모델 디렉터리 (기본 backend/models/onnx-int8)

기본 모델은 KoELECTRA-small-v3를 NSMC(네이버 영화 리뷰)로 파인튜닝한 14.1M 파라미터 모델이다.
저장소에는 이를 INT8로 양자화한 ONNX(14.2MB)가 함께 커밋돼 있어, 배포 환경에서 별도 다운로드
없이 onnxruntime만으로 바로 서빙된다. 선정 근거와 실측값은 README "모델 경량화" 절 참고.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MODEL_ID = os.getenv("SENTIMENT_MODEL", "daekeun-ml/koelectra-small-v3-nsmc")
BACKEND = os.getenv("SENTIMENT_BACKEND", "auto").lower()
ONNX_DIR = Path(os.getenv("ONNX_MODEL_DIR", BASE_DIR / "models" / "onnx-int8"))
MAX_LEN = 128

# ---------------------------------------------------------------- 규칙 기반 사전
POSITIVE_WORDS = {
    "최고", "감동", "명작", "훌륭", "재미있", "재밌", "좋았", "좋다", "좋은", "웰메이드",
    "인생영화", "추천", "완벽", "몰입", "탄탄", "수작", "빛나", "황홀", "만족", "대박",
    "걸작", "신선", "따뜻", "울었", "여운", "압도", "미쳤", "갓작", "행복", "사랑",
}
NEGATIVE_WORDS = {
    "최악", "지루", "노잼", "실망", "별로", "아깝", "졸작", "망작", "억지", "어색",
    "지겹", "산만", "루즈", "불편", "형편없", "안타깝", "실패", "끔찍", "짜증", "후회",
    "돈아까", "시간낭비", "발연기", "엉성", "유치", "뻔한", "지루했", "재미없",
}
NEGATION = ("안 ", "않", "못 ", "없")


class SentimentAnalyzer:
    """지연 로딩 + 스레드 안전 싱글턴 감성 분석기."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded = False
        self._backend = "lexicon"
        self._model_name = "lexicon-rule"
        self._session = None      # ONNX InferenceSession
        self._input_names: set[str] = set()
        self._tokenizer = None
        self._pipe = None         # transformers pipeline
        self._positive_index = 1  # 긍정 라벨의 로짓 인덱스

    # ------------------------------------------------------------ 모델 로딩
    def _load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            order = {
                "auto": ["onnx", "transformers", "lexicon"],
                "onnx": ["onnx", "lexicon"],
                "transformers": ["transformers", "lexicon"],
                "lexicon": ["lexicon"],
            }.get(BACKEND, ["onnx", "transformers", "lexicon"])

            for backend in order:
                try:
                    if backend == "onnx" and self._load_onnx():
                        break
                    if backend == "transformers" and self._load_torch():
                        break
                    if backend == "lexicon":
                        self._backend, self._model_name = "lexicon", "lexicon-rule"
                        logger.warning("감성 분석: 규칙 기반 폴백으로 동작합니다.")
                        break
                except Exception as exc:  # noqa: BLE001
                    logger.warning("감성 백엔드 '%s' 로딩 실패: %s", backend, exc)
            self._loaded = True

    def _load_onnx(self) -> bool:
        model_file = ONNX_DIR / "model.onnx"
        if not model_file.exists():
            return False
        import onnxruntime as ort  # noqa: PLC0415
        from tokenizers import Tokenizer  # noqa: PLC0415

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1  # 컨테이너 환경에서 오버서브스크립션 방지
        self._session = ort.InferenceSession(
            str(model_file), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self._input_names = {i.name for i in self._session.get_inputs()}
        # tokenizer.json에 정규화·분절 규칙이 모두 들어 있어 transformers(약 73MB) 없이
        # tokenizers(약 7MB)만으로 동일한 결과를 얻는다.
        self._tokenizer = Tokenizer.from_file(str(ONNX_DIR / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=MAX_LEN)
        self._backend, self._model_name = "onnx", f"{MODEL_ID} (ONNX INT8)"
        logger.info("감성 분석: ONNX INT8 모델 로딩 완료")
        return True

    def _load_torch(self) -> bool:
        import torch  # noqa: PLC0415
        from transformers import pipeline  # noqa: PLC0415

        torch.set_num_threads(1)
        self._pipe = pipeline(
            "text-classification",
            model=MODEL_ID,
            top_k=None,
            truncation=True,
            max_length=MAX_LEN,
            device=-1,
        )
        self._backend, self._model_name = "transformers", MODEL_ID
        logger.info("감성 분석: transformers 모델(%s) 로딩 완료", MODEL_ID)
        return True

    # ------------------------------------------------------------ 추론
    def predict(self, text: str) -> dict:
        self._load()
        text = (text or "").strip()
        if not text:
            return {"label": "negative", "score": 0.5, "model": self._model_name}

        if self._backend == "onnx":
            score = self._predict_onnx(text)
        elif self._backend == "transformers":
            score = self._predict_torch(text)
        else:
            score = self._predict_lexicon(text)

        return {
            "label": "positive" if score >= 0.5 else "negative",
            "score": round(float(score), 4),
            "model": self._model_name,
        }

    def _predict_onnx(self, text: str):
        import numpy as np  # noqa: PLC0415

        enc = self._tokenizer.encode(text)
        # 한 문장씩 추론하므로 패딩 없이 실제 길이만 넣는다(고정 128 패딩보다 빠르다).
        arrays = {
            "input_ids": enc.ids,
            "attention_mask": enc.attention_mask,
            "token_type_ids": enc.type_ids,
        }
        feed = {
            name: np.array([values], dtype=np.int64)
            for name, values in arrays.items()
            if name in self._input_names
        }
        logits = self._session.run(None, feed)[0][0]
        exp = np.exp(logits - logits.max())
        probs = exp / exp.sum()
        return probs[self._positive_index] if len(probs) > 1 else probs[0]

    def _predict_torch(self, text: str):
        outputs = self._pipe(text)[0]  # [{'label': 'LABEL_1', 'score': 0.98}, ...]
        best = max(outputs, key=lambda d: d["score"])
        return best["score"] if _is_positive(best["label"]) else 1.0 - best["score"]

    @staticmethod
    def _predict_lexicon(text: str) -> float:
        clauses = [c for c in re.split(r"[,.!?~\n]| 하지만 | 그러나 ", text) if c.strip()]
        pos = neg = 0
        for clause in clauses:
            p = sum(1 for w in POSITIVE_WORDS if w in clause)
            n = sum(1 for w in NEGATIVE_WORDS if w in clause)
            # "지루할 틈이 없었다", "재미있지 않다" 처럼 부정어가 붙으면 극성을 뒤집는다
            if any(x in clause for x in NEGATION) and (p or n):
                p, n = n, p
            pos, neg = pos + p, neg + n
        if pos == neg == 0:
            return 0.5
        raw = (pos - neg) / (pos + neg)
        return min(max(0.5 + raw * 0.45, 0.02), 0.98)

    @property
    def info(self) -> dict:
        self._load()
        return {"backend": self._backend, "model": self._model_name}


def _is_positive(label: str) -> bool:
    """모델마다 다른 라벨 표기를 통일한다."""
    label = str(label).lower()
    if label in {"label_1", "1", "positive", "pos", "긍정"}:
        return True
    if label in {"label_0", "0", "negative", "neg", "부정"}:
        return False
    return "pos" in label or "긍" in label


analyzer = SentimentAnalyzer()
