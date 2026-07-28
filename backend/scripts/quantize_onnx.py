"""감성 분석 모델 경량화 스크립트.

PyTorch 체크포인트 → ONNX 변환 → 동적 양자화(INT8) 를 수행한다.

    python scripts/quantize_onnx.py                          # 기본 모델(KoELECTRA-small)
    python scripts/quantize_onnx.py --model <HF_ID> --out <dir>
    SENTIMENT_BACKEND=onnx uvicorn app.main:app --port 8000

실측값(NSMC test 1,000건 · CPU 1스레드)은 README "모델 경량화" 절 참고.
동적 양자화는 가중치만 INT8로 미리 바꾸고 활성값은 추론 시점에 스케일을 잡는다.
보정(calibration) 데이터가 필요 없어 정확도 손실이 작고 파이프라인이 단순하다.
"""

import argparse
import sys
from pathlib import Path

# Windows 콘솔 기본 인코딩(cp949)에서 유니코드 기호가 깨지지 않도록 한다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from optimum.onnxruntime import ORTModelForSequenceClassification, ORTQuantizer
from optimum.onnxruntime.configuration import AutoQuantizationConfig
from transformers import AutoTokenizer

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "daekeun-ml/koelectra-small-v3-nsmc"


def main() -> None:
    parser = argparse.ArgumentParser(description="ONNX 변환 + INT8 동적 양자화")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="HuggingFace 모델 ID")
    parser.add_argument("--out", default=str(BASE_DIR / "models" / "onnx-int8"),
                        help="INT8 모델 저장 경로")
    parser.add_argument("--keep-fp32", action="store_true",
                        help="중간 산출물인 FP32 ONNX를 지우지 않는다 (크기 비교용)")
    args = parser.parse_args()

    int8_dir = Path(args.out)
    fp32_dir = int8_dir.parent / "onnx-fp32"

    print(f"[1/4] {args.model} → ONNX(FP32) 변환")
    model = ORTModelForSequenceClassification.from_pretrained(args.model, export=True)
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model.save_pretrained(fp32_dir)
    tokenizer.save_pretrained(fp32_dir)
    fp32_mb = (fp32_dir / "model.onnx").stat().st_size / 1024**2

    print("[2/4] 동적 양자화(INT8) — 가중치만 INT8, 활성값은 런타임 계산")
    quantizer = ORTQuantizer.from_pretrained(fp32_dir)
    qconfig = AutoQuantizationConfig.avx512_vnni(is_static=False, per_channel=True)
    quantizer.quantize(save_dir=int8_dir, quantization_config=qconfig)
    tokenizer.save_pretrained(int8_dir)

    print("[3/4] 파일명 정규화 (analyzer가 model.onnx를 찾는다)")
    target = int8_dir / "model.onnx"
    for candidate in int8_dir.glob("*quantized*.onnx"):
        candidate.replace(target)
        break
    int8_mb = target.stat().st_size / 1024**2

    if not args.keep_fp32:
        for f in fp32_dir.glob("*"):
            f.unlink()
        fp32_dir.rmdir()

    print("[4/4] 크기 비교")
    print(f"    FP32: {fp32_mb:6.1f} MB")
    print(f"    INT8: {int8_mb:6.1f} MB  ({fp32_mb / int8_mb:.2f}x 축소)")
    print(f"완료 → {int8_dir}")


if __name__ == "__main__":
    main()
