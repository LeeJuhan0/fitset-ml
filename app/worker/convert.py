import os
import shutil

import torch
from app.worker.model_def import FitSetModel, WrappedModel


def to_mlpackage(model: FitSetModel, mean: list, std: list, out_path: str) -> str:
    """iOS — CoreML .mlpackage 변환 후 zip 압축. zip 파일 경로를 반환한다.

    .mlpackage는 단일 파일이 아니라 디렉토리 번들이라 S3 단일 업로드가 안 된다.
    → 'FitSet.mlpackage/'가 루트에 오도록 디렉토리째 zip으로 묶는다.
    앱은 zip을 받아 풀고 MLModel.compileModel로 .mlmodelc 컴파일 후 로드한다.
    out_path='/tmp/FitSet.mlpackage' → 산출물 '/tmp/FitSet.mlpackage.zip' 반환.
    """
    import coremltools as ct

    wrapped = WrappedModel(model, mean, std).eval()
    example = torch.zeros(1, 200, 6)
    traced = torch.jit.trace(wrapped, example)

    mlmodel = ct.convert(
        traced,
        inputs=[ct.TensorType(name="imu_window", shape=example.shape)],
        outputs=[ct.TensorType(name="probs")],
        minimum_deployment_target=ct.target.watchOS8,
        compute_precision=ct.precision.FLOAT32,   # 학습(FP32)과 일치 — 기본 FP16 다운캐스트 방지
    )
    mlmodel.save(out_path)                          # .mlpackage 디렉토리 생성

    # 디렉토리 구조 보존하며 zip ('FitSet.mlpackage/...'가 zip 루트에 위치)
    return shutil.make_archive(
        out_path, "zip",
        root_dir=os.path.dirname(out_path),
        base_dir=os.path.basename(out_path),
    )                                               # → '/tmp/FitSet.mlpackage.zip'


def to_tflite(model: FitSetModel, mean: list, std: list, out_path: str):
    """Android — TFLite 변환 (ai.edge.torch)"""
    import ai.edge.torch as edge_torch

    wrapped = WrappedModel(model, mean, std).eval()
    example = torch.zeros(1, 200, 6)
    edge_model = edge_torch.convert(wrapped, (example,))
    edge_model.export(out_path)
