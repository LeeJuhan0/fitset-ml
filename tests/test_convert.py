import os
import sys
import types
import zipfile

import pytest


def _install_fake_coremltools(monkeypatch, captured):
    """ct.convert(...).save(path) 가 가짜 .mlpackage 디렉토리를 만들도록 한다"""
    ct = types.ModuleType("coremltools")

    class _Model:
        def save(self, path):
            os.makedirs(path, exist_ok=True)
            with open(os.path.join(path, "Manifest.json"), "w") as f:
                f.write("{}")
            data_dir = os.path.join(path, "Data")
            os.makedirs(data_dir, exist_ok=True)
            with open(os.path.join(data_dir, "weights.bin"), "wb") as f:
                f.write(b"\x00\x01")

    def convert(traced, inputs=None, outputs=None,
                minimum_deployment_target=None, compute_precision=None):
        captured["compute_precision"] = compute_precision
        captured["inputs"] = inputs
        captured["outputs"] = outputs
        return _Model()

    ct.convert = convert
    ct.TensorType = lambda name=None, shape=None: {"name": name, "shape": shape}
    ct.precision = types.SimpleNamespace(FLOAT32="FLOAT32", FLOAT16="FLOAT16")
    ct.target = types.SimpleNamespace(watchOS8="watchOS8")
    monkeypatch.setitem(sys.modules, "coremltools", ct)


def test_to_mlpackage_returns_zip_with_preserved_structure(tmp_path, monkeypatch):
    captured = {}
    _install_fake_coremltools(monkeypatch, captured)

    from app.worker.convert import to_mlpackage
    from app.worker.model_def import FitSetModel

    out = str(tmp_path / "FitSet.mlpackage")
    zip_path = to_mlpackage(FitSetModel(num_classes=5), [0.0] * 6, [1.0] * 6, out)

    assert zip_path == out + ".zip"
    assert os.path.exists(zip_path)

    assert captured["compute_precision"] == "FLOAT32"

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert any(n.startswith("FitSet.mlpackage/") for n in names)
    assert any(n.endswith("FitSet.mlpackage/Manifest.json") for n in names)
    assert any(n.endswith("Data/weights.bin") for n in names)


def test_to_mlpackage_input_output_feature_names(tmp_path, monkeypatch):
    captured = {}
    _install_fake_coremltools(monkeypatch, captured)

    from app.worker.convert import to_mlpackage
    from app.worker.model_def import FitSetModel

    out = str(tmp_path / "FitSet.mlpackage")
    to_mlpackage(FitSetModel(num_classes=5), [0.0] * 6, [1.0] * 6, out)

    assert captured["inputs"][0]["name"] == "imu_window"
    assert tuple(captured["inputs"][0]["shape"]) == (1, 200, 6)
    assert captured["outputs"][0]["name"] == "probs"


def test_to_onnx_matches_app_contract(tmp_path):
    onnxruntime = pytest.importorskip("onnxruntime")
    import numpy as np

    from app.worker.convert import to_onnx
    from app.worker.model_def import FitSetModel

    out = str(tmp_path / "FitSet.onnx")
    to_onnx(FitSetModel(num_classes=5), [0.0] * 6, [1.0] * 6, out)

    session = onnxruntime.InferenceSession(out)
    assert session.get_inputs()[0].name == "imu_window"
    assert session.get_inputs()[0].shape == [1, 200, 6]
    assert session.get_outputs()[0].name == "probs"

    probs = session.run(None, {"imu_window": np.zeros((1, 200, 6), dtype=np.float32)})[0]
    assert probs.shape == (1, 5)
    assert abs(float(probs.sum()) - 1.0) < 1e-4
