"""모델 변환 (app.worker.convert) — coremltools를 가짜로 주입해 zip 패키징을 검증.

coremltools는 환경에 따라 설치가 어려워(주로 macOS) 실제 변환은 돌릴 수 없다.
대신 `import coremltools as ct`가 받는 모듈을 가짜로 끼워, to_mlpackage가
① FP32로 변환 요청하는지, ② .mlpackage 디렉토리를 'FitSet.mlpackage/' 구조
보존하며 zip으로 묶어 그 경로를 반환하는지를 단위로 검증한다.
"""

import os
import sys
import types
import zipfile

import pytest


def _install_fake_coremltools(monkeypatch, captured):
    """ct.convert(...).save(path) 가 가짜 .mlpackage 디렉토리를 만들도록 한다."""
    ct = types.ModuleType("coremltools")

    class _Model:
        def save(self, path):
            os.makedirs(path, exist_ok=True)
            # .mlpackage 번들의 대표 파일 — zip 구조 보존 확인용
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

    # 반환값은 zip 경로
    assert zip_path == out + ".zip"
    assert os.path.exists(zip_path)

    # 학습(FP32)과 일치하도록 FP32로 변환 요청했는지
    assert captured["compute_precision"] == "FLOAT32"

    # zip 루트에 'FitSet.mlpackage/' 구조가 보존됐는지 (앱이 풀어서 compile 가능)
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

    # 앱 추론 계약: 입력 imu_window[1,200,6], 출력 probs
    assert captured["inputs"][0]["name"] == "imu_window"
    assert tuple(captured["inputs"][0]["shape"]) == (1, 200, 6)
    assert captured["outputs"][0]["name"] == "probs"
