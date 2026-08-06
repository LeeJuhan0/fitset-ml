# ─────────────────────────────────────────────────────────────────────────────
# 모델 변환 — trainer.py의 4단계에서 호출. 학습된 PyTorch 모델을 온디바이스 포맷으로 바꾼다.
#   iOS  → CoreML(.mlpackage),  Android → ONNX(.onnx, 앱은 ONNX Runtime으로 로드)
# 두 함수 모두 WrappedModel(정규화+softmax 내장)로 감싼 뒤 export → 앱은 raw IMU만 넣으면 됨.
# ─────────────────────────────────────────────────────────────────────────────
import os
import shutil   # 디렉토리 zip 압축에 사용

import torch
from app.worker.model_def import FitSetModel, WrappedModel


def to_mlpackage(model: FitSetModel, mean: list, std: list, out_path: str) -> str:
    """iOS — CoreML .mlpackage 변환 후 zip 압축. zip 파일 경로를 반환한다.

    .mlpackage는 단일 파일이 아니라 디렉토리 번들이라 S3 단일 업로드가 안 된다.
    → 'FitSet.mlpackage/'가 루트에 오도록 디렉토리째 zip으로 묶는다.
    앱은 zip을 받아 풀고 MLModel.compileModel로 .mlmodelc 컴파일 후 로드한다.
    out_path='/tmp/FitSet.mlpackage' → 산출물 '/tmp/FitSet.mlpackage.zip' 반환.
    """
    # 인자: model=학습된 FitSetModel, mean/std=정규화 통계(6개), out_path=저장 경로(.mlpackage)
    import coremltools as ct   # 무거운 의존성이라 함수 안에서 import(없으면 trainer가 ImportError로 처리)

    wrapped = WrappedModel(model, mean, std).eval()   # 정규화+softmax 감싸고 추론 모드로
    example = torch.zeros(1, 200, 6)                   # 예시 입력(형태만 필요) — 추적용 더미 [1,200,6]
    traced = torch.jit.trace(wrapped, example)         # 모델 실행을 따라가며 정적 그래프로 기록(trace)

    # ct.convert: TorchScript → CoreML 모델로 변환. inputs/outputs는 텐서 이름·형태 명세.
    mlmodel = ct.convert(
        traced,
        inputs=[ct.TensorType(name="imu_window", shape=example.shape)],   # 입력 텐서 정의(이름·shape)
        outputs=[ct.TensorType(name="probs")],                            # 출력 텐서 이름(확률)
        minimum_deployment_target=ct.target.watchOS8,                     # 최소 지원 watchOS 버전
        compute_precision=ct.precision.FLOAT32,   # 학습(FP32)과 일치 — 기본 FP16 다운캐스트 방지
    )
    mlmodel.save(out_path)                          # .mlpackage 디렉토리 생성

    # 디렉토리 구조 보존하며 zip ('FitSet.mlpackage/...'가 zip 루트에 위치)
    # shutil.make_archive(base, format, root_dir, base_dir) → 만들어진 zip 경로 문자열 반환
    return shutil.make_archive(
        out_path, "zip",                       # zip 파일명 베이스, 포맷
        root_dir=os.path.dirname(out_path),    # 압축 기준 디렉토리
        base_dir=os.path.basename(out_path),   # zip 안에 담길 최상위 폴더명(FitSet.mlpackage)
    )                                               # → '/tmp/FitSet.mlpackage.zip'


def to_onnx(model: FitSetModel, mean: list, std: list, out_path: str):
    """Android — ONNX 변환. 앱(ExerciseClassifier.kt)이 ONNX Runtime으로 로드한다.

    입출력 계약은 iOS와 동일 — 입력 imu_window[1,200,6], 출력 probs.
    (구 TFLite 경로는 ai-edge-torch가 TF 스택을 동반해 t3.small에서 못 돌아 폐기, ONNX로 대체.)
    """
    # 인자는 to_mlpackage와 동일. out_path=.onnx 파일 경로. 반환값 없음(파일로 떨굼).
    import onnx   # noqa: F401 — torch.onnx.export가 요구(없으면 ImportError로 trainer가 건너뜀)

    wrapped = WrappedModel(model, mean, std).eval()   # 동일하게 정규화+softmax 감싸기
    example = torch.zeros(1, 200, 6)                   # 더미 입력
    torch.onnx.export(
        wrapped,
        (example,),
        out_path,
        input_names=["imu_window"],    # 앱이 이 이름으로 텐서를 넣는다
        output_names=["probs"],        # 확률 벡터(softmax 내장)
        dynamo=False,                  # 레거시 exporter 고정 — 텐서 이름·그래프가 결정적
    )
