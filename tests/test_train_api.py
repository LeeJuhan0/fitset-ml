from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from conftest import async_
import app.training.service as train_mod


@pytest.fixture(autouse=True)
def reset_running():
    train_mod._running.clear()
    yield
    train_mod._running.clear()


def _fake_mlflow(run_id="run-xyz"):
    fake_client = MagicMock()
    fake_client.get_experiment_by_name.return_value = SimpleNamespace(experiment_id="exp-1")
    fake_client.create_run.return_value = SimpleNamespace(info=SimpleNamespace(run_id=run_id))
    return SimpleNamespace(
        set_tracking_uri=lambda uri: None,
        MlflowClient=lambda: fake_client,
    )


def test_train_400_on_unknown_file(admin_client, monkeypatch):
    monkeypatch.setattr(train_mod, "uploaded_filenames", async_(lambda s, p: {"a.csv"}))
    resp = admin_client.post("/api/v1/ios/train", json={"files": ["a.csv", "ghost.csv"]})
    assert resp.status_code == 400
    assert "ghost.csv" in resp.json()["error"]["message"]


def test_train_400_on_not_uploaded_file(admin_client, monkeypatch):
    monkeypatch.setattr(train_mod, "uploaded_filenames", async_(lambda s, p: {"a.csv"}))
    resp = admin_client.post("/api/v1/ios/train", json={"files": ["a.csv", "pending.csv"]})
    assert resp.status_code == 400
    assert "pending.csv" in resp.json()["error"]["message"]


def test_train_409_when_already_running(admin_client):
    busy = MagicMock()
    busy.poll.return_value = None
    train_mod._running["ios"] = {"process": busy}

    resp = admin_client.post("/api/v1/ios/train", json={"files": ["a.csv"]})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CONFLICT"
    assert resp.headers["X-Trace-Id"] == resp.json()["traceId"]


def test_train_202_spawns_worker(admin_client, monkeypatch):
    monkeypatch.setattr(train_mod, "uploaded_filenames", async_(lambda s, p: {"a.csv"}))
    monkeypatch.setattr(train_mod, "next_version", lambda p: "v1.4")
    monkeypatch.setattr(train_mod, "mlflow", _fake_mlflow(run_id="run-xyz"))

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    spawned = {}

    def fake_popen(args, **kwargs):
        spawned["args"] = args
        return fake_proc

    monkeypatch.setattr(train_mod, "subprocess", SimpleNamespace(Popen=fake_popen))

    resp = admin_client.post("/api/v1/ios/train", json={"files": ["a.csv"], "epochs": 50, "lr": 0.01})
    assert resp.status_code == 202

    data = resp.json()["data"]
    assert data["jobId"] == "run-xyz"
    assert data["version"] == "v1.4"
    assert data["totalEpochs"] == 50

    assert "app.worker.trainer" in spawned["args"]
    assert "--platform" in spawned["args"] and "ios" in spawned["args"]
    assert train_mod._running["ios"]["job_id"] == "run-xyz"


def test_train_uses_default_epochs_and_lr(admin_client, monkeypatch):
    monkeypatch.setattr(train_mod, "uploaded_filenames", async_(lambda s, p: {"a.csv"}))
    monkeypatch.setattr(train_mod, "next_version", lambda p: "v1.0")
    monkeypatch.setattr(train_mod, "mlflow", _fake_mlflow())
    proc = MagicMock(); proc.poll.return_value = None
    monkeypatch.setattr(train_mod, "subprocess", SimpleNamespace(Popen=lambda *a, **k: proc))

    resp = admin_client.post("/api/v1/ios/train", json={"files": ["a.csv"]})
    assert resp.status_code == 202
    assert resp.json()["data"]["totalEpochs"] == 200


def test_train_status_maps_running(admin_client, monkeypatch):
    run = SimpleNamespace(
        info=SimpleNamespace(status="RUNNING", experiment_id="exp-1"),
        data=SimpleNamespace(metrics={"epoch": 12, "train_loss": 0.4, "val_loss": 0.5, "val_accuracy": 0.8}),
    )
    fake_client = MagicMock()
    fake_client.get_run.return_value = run
    monkeypatch.setattr(
        train_mod, "mlflow",
        SimpleNamespace(set_tracking_uri=lambda u: None, MlflowClient=lambda: fake_client),
    )
    train_mod._running["ios"] = {"total_epochs": 100}

    resp = admin_client.get("/api/v1/ios/train/status?jobId=run-xyz")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "running"
    assert data["epoch"] == 12
    assert data["totalEpochs"] == 100
    assert data["valAccuracy"] == 0.8


def test_train_status_404_on_unknown_job(admin_client, monkeypatch):
    fake_client = MagicMock()
    fake_client.get_run.side_effect = Exception("not found")
    monkeypatch.setattr(
        train_mod, "mlflow",
        SimpleNamespace(set_tracking_uri=lambda u: None, MlflowClient=lambda: fake_client),
    )
    resp = admin_client.get("/api/v1/ios/train/status?jobId=missing")
    assert resp.status_code == 404
