from conftest import async_
import app.phase.service as phase_mod
from app.data.models import DatasetFileRead
from app.phase.models import PhaseModelRead


def _dataset(filename="PUSHUP_DEV1_0001.parquet"):
    return DatasetFileRead(id=7, filename=filename, class_name="PUSHUP", device_id="DEV1", bucket="fitset-dataset",
                           s3_key=f"ios/raw/PUSHUP/{filename}", uploaded=True, phase_labeled=True,
                           created_at="2026-09-22T02:00:00+00:00")


def test_train_validates_class_and_files(admin_client, monkeypatch):
    assert admin_client.post("/api/v1/ios/phase/train", json={"class": "DEADLIFT"}).status_code == 400
    monkeypatch.setattr(phase_mod, "phase_labeled_files", async_(lambda s, p, c: []))
    resp = admin_client.post("/api/v1/ios/phase/train", json={"class": "PUSHUP"})
    assert resp.status_code == 400 and "phase 라벨 파일이 없습니다" in resp.json()["error"]["message"]


def test_train_creates_model_and_spawns(admin_client, monkeypatch):
    monkeypatch.setattr(phase_mod, "phase_labeled_files", async_(lambda s, p, c: [_dataset(), _dataset("PUSHUP_DEV1_0002.parquet")]))
    monkeypatch.setattr(phase_mod, "phase_model_versions", async_(lambda s, p, c: ["v1.0", "v1.1"]))
    created, spawned = {}, {}
    def fake_create(s, p, c, version, files, **kw):
        created.update(version=version, files=files, **kw)
        return PhaseModelRead(id=3, platform=p, class_name=c, version=version, bucket="fitset-phase-models",
                              created_at="2026-09-22T03:00:00+00:00")
    monkeypatch.setattr(phase_mod, "create_phase_model", async_(fake_create))
    monkeypatch.setattr(phase_mod, "spawn_trainer", lambda *a, **kw: spawned.update(args=a, kw=kw))

    resp = admin_client.post("/api/v1/ios/phase/train", json={"class": "PUSHUP", "epochs": 5})
    assert resp.status_code == 202
    data = resp.json()["data"]
    assert data == {"modelId": 3, "version": "v1.2", "class": "PUSHUP", "numFiles": 2}
    assert created["files"] == ["PUSHUP_DEV1_0001.parquet", "PUSHUP_DEV1_0002.parquet"] and created["epochs"] == 5 and created["lr"] == 0.001
    assert spawned["args"][2] == 3 and spawned["kw"]["window"] == 50


def test_models_list_and_download_url(admin_client, monkeypatch):
    model = PhaseModelRead(id=3, platform="ios", class_name="PUSHUP", version="v1.0", status="completed",
                           bucket="fitset-phase-models", pt_key="ios/PUSHUP/v1.0/FitSetPhase.pt", onnx_key=None,
                           metrics={"final": {"macro_f1": 0.9}}, created_at="2026-09-22T03:00:00+00:00")
    monkeypatch.setattr(phase_mod, "list_phase_models", async_(lambda s, p, c=None: [model]))
    monkeypatch.setattr(phase_mod, "get_phase_model", async_(lambda s, p, i: model if i == 3 else None))
    monkeypatch.setattr(phase_mod, "presigned_get_url", lambda b, k, e: f"https://signed/{b}/{k}")

    resp = admin_client.get("/api/v1/ios/phase/models?class=PUSHUP")
    assert resp.status_code == 200
    assert resp.json()["data"]["models"][0]["class"] == "PUSHUP"
    assert resp.json()["data"]["models"][0]["canDownload"] is True
    assert resp.json()["data"]["models"][0]["metrics"]["final"]["macro_f1"] == 0.9

    ok = admin_client.get("/api/v1/ios/phase/models/3/download-url?format=pt")
    assert ok.status_code == 200 and ok.json()["data"]["url"].endswith("FitSetPhase.pt")
    assert admin_client.get("/api/v1/ios/phase/models/3/download-url?format=onnx").status_code == 404
    assert admin_client.get("/api/v1/ios/phase/models/9/download-url?format=pt").status_code == 404
    assert admin_client.get("/api/v1/ios/phase/models/3/download-url?format=tflite").status_code == 400


def test_deploy_requires_completed_model_and_env(admin_client, monkeypatch):
    done = PhaseModelRead(id=3, platform="ios", class_name="PUSHUP", version="v1.0", status="completed",
                          bucket="fitset-phase-models", pt_key="k.pt", mlpackage_key="k.mlpackage.zip",
                          created_at="2026-09-22T03:00:00+00:00")
    training = PhaseModelRead(id=4, platform="ios", class_name="PUSHUP", version="v1.1", status="training",
                              bucket="fitset-phase-models", created_at="2026-09-22T03:00:00+00:00")
    calls = []
    monkeypatch.setattr(phase_mod, "get_phase_model", async_(lambda s, p, i: {3: done, 4: training}.get(i)))
    monkeypatch.setattr(phase_mod, "deploy_phase_model", async_(lambda s, p, i, env: calls.append(env) or done))

    ok = admin_client.post("/api/v1/ios/phase/models/3/deploy", json={"env": "prod"})
    assert ok.status_code == 200 and ok.json()["data"]["version"] == "v1.0" and calls == ["prod"]
    assert admin_client.post("/api/v1/ios/phase/models/3/deploy", json={}).status_code == 400
    assert admin_client.post("/api/v1/ios/phase/models/3/deploy", json={"env": "stage"}).status_code == 400
    assert admin_client.post("/api/v1/ios/phase/models/4/deploy", json={"env": "dev"}).status_code == 404
    assert admin_client.post("/api/v1/ios/phase/models/9/deploy", json={"env": "dev"}).status_code == 404


def test_dead_phase_trainer_marked_failed(admin_client, monkeypatch):
    from unittest.mock import MagicMock
    from app.core.utils import LOST_PROCESS_ERROR

    def model(i, status):
        return PhaseModelRead(id=i, platform="ios", class_name="PUSHUP", version=f"v1.{i}", status=status,
                              bucket="fitset-phase-models", created_at="2026-09-22T03:00:00+00:00")
    rows = [model(1, "training"), model(2, "training"), model(3, "training"), model(4, "completed")]
    monkeypatch.setattr(phase_mod, "list_phase_models", async_(lambda s, p, c=None: rows))
    failed = {}
    monkeypatch.setattr(phase_mod, "fail_phase_model", async_(lambda s, i, e: failed.update({i: e})))
    alive, oom = MagicMock(), MagicMock()
    alive.poll.return_value = None
    oom.poll.return_value = oom.returncode = -9
    monkeypatch.setattr(phase_mod, "_trainer_procs", {1: alive, 2: oom})

    assert admin_client.get("/api/v1/ios/phase/models").status_code == 200
    assert set(failed) == {2, 3}
    assert "OOM" in failed[2] and failed[3] == LOST_PROCESS_ERROR
    assert list(phase_mod._trainer_procs) == [1]


def test_predict_aligns_frames_and_marks_val_start(admin_client, monkeypatch, tmp_path):
    import json
    import shutil

    import numpy as np
    import pandas as pd
    import torch

    from app.labeling.models import CollectFileRead, PhaseLabelRead
    from app.worker.model_def import FitSetModel

    model = PhaseModelRead(id=3, platform="ios", class_name="PUSHUP", version="v1.0", status="completed", window=20,
                           bucket="fitset-phase-models", pt_key="m.pt", meta_key="meta.json", created_at="2026-09-22T03:00:00+00:00")
    label = PhaseLabelRead(data_bucket="b", data_key="d.parquet", video_bucket="b", video_key="v", pose_key="p",
                           phase_summary={"fps": 10.0, "frames": 12}, labeled_at="2026-09-22T01:00:00+00:00")
    entry = CollectFileRead(filename="PUSHUP_DEV1_0001.csv", class_name="PUSHUP", device_id="DEV1", csv_bucket="c", csv_key="c",
                            video_bucket="v", video_key="v", uploaded=True, video_start=1000.0, rows=100, status="labeled",
                            created_at="2026-09-22T00:00:00+00:00", label=label)
    torch.save(FitSetModel(num_classes=2).state_dict(), tmp_path / "m.pt")
    n = 100
    pd.DataFrame({"timestamp": 1000.0 + np.arange(n) * 0.01, **{c: np.random.randn(n) for c in ["ax", "ay", "az", "gx", "gy", "gz"]},
                  "phase": np.repeat([0, 1, 0, 1], 25)}).to_parquet(tmp_path / "d.parquet")
    meta = {"classes": ["down", "up"], "window": 20, "mean": [0.0] * 6, "std": [1.0] * 6, "trained_files": ["PUSHUP_DEV1_0001.parquet"]}
    monkeypatch.setattr(phase_mod, "get_phase_model", async_(lambda s, p, i: model if i == 3 else None))
    monkeypatch.setattr(phase_mod, "get_file", async_(lambda s, p, f: entry if f == entry.filename else None))
    monkeypatch.setattr(phase_mod.s3, "get_object_bytes", lambda b, k: json.dumps(meta).encode())
    monkeypatch.setattr(phase_mod.s3, "download_object", lambda b, k, dst: shutil.copy(tmp_path / k, dst))

    resp = admin_client.get("/api/v1/ios/phase/models/3/predict?filename=PUSHUP_DEV1_0001.csv")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["version"] == "v1.0" and data["fps"] == 10.0 and len(data["frames"]) == 12
    assert data["labelCount"] == 2 and data["valStartFrame"] == 8
    assert data["frames"][0] == -1 and data["frames"][1] in (0, 1) and data["frames"][10:] == [-1, -1]

    assert admin_client.get("/api/v1/ios/phase/models/9/predict?filename=PUSHUP_DEV1_0001.csv").status_code == 404
    assert admin_client.get("/api/v1/ios/phase/models/3/predict?filename=OTHER.csv").status_code == 404
