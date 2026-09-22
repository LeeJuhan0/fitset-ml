import os
import shutil

import torch
from app.worker.model_def import FitSetModel, WrappedModel


def to_mlpackage(model: FitSetModel, mean: list, std: list, out_path: str, window: int = 200) -> str:
    """CoreML mlpackage 변환 후 zip, 경로 반환"""
    import coremltools as ct

    wrapped = WrappedModel(model, mean, std).eval()
    example = torch.zeros(1, window, 6)
    traced = torch.jit.trace(wrapped, example)

    mlmodel = ct.convert(
        traced,
        inputs=[ct.TensorType(name="imu_window", shape=example.shape)],
        outputs=[ct.TensorType(name="probs")],
        minimum_deployment_target=ct.target.watchOS8,
        compute_precision=ct.precision.FLOAT32,
    )
    mlmodel.save(out_path)

    return shutil.make_archive(
        out_path, "zip",
        root_dir=os.path.dirname(out_path),
        base_dir=os.path.basename(out_path),
    )


def to_onnx(model: FitSetModel, mean: list, std: list, out_path: str, window: int = 200):
    """Android — ONNX 변환. 앱(ExerciseClassifier.kt)이 ONNX Runtime으로 로드한다"""
    import onnx

    wrapped = WrappedModel(model, mean, std).eval()
    example = torch.zeros(1, window, 6)
    torch.onnx.export(
        wrapped,
        (example,),
        out_path,
        input_names=["imu_window"],
        output_names=["probs"],
        dynamo=False,
    )
