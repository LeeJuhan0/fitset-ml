import torch
from app.worker.model_def import FitSetModel, WrappedModel


def to_mlpackage(model: FitSetModel, mean: list, std: list, out_path: str):
    """iOS — CoreML .mlpackage 변환"""
    import coremltools as ct

    wrapped = WrappedModel(model, mean, std).eval()
    example = torch.zeros(1, 200, 6)
    traced = torch.jit.trace(wrapped, example)

    mlmodel = ct.convert(
        traced,
        inputs=[ct.TensorType(name="imu_window", shape=example.shape)],
        outputs=[ct.TensorType(name="probs")],
        minimum_deployment_target=ct.target.watchOS8,
    )
    mlmodel.save(out_path)


def to_tflite(model: FitSetModel, mean: list, std: list, out_path: str):
    """Android — TFLite 변환 (ai.edge.torch)"""
    import ai.edge.torch as edge_torch

    wrapped = WrappedModel(model, mean, std).eval()
    example = torch.zeros(1, 200, 6)
    edge_model = edge_torch.convert(wrapped, (example,))
    edge_model.export(out_path)
