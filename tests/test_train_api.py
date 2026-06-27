"""학습 시작/진행률 라우터 (app.api.train) — MLflow·subprocess·S3 가짜 대체.

학습 워커 spawn(subprocess)과 MLflow run 생성은 부수효과이므로 모두 가짜로 막고,
입력 검증(존재하지 않는 파일 400, 중복 학습 409)과 상태 매핑만 검증한다."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.api.train as train_mod


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


def test_train_400_on_unknown_file(client, monkeypatch):
    monkeypatch.setattr(train_mod, "get_index", lambda p: {"files": [{"filename": "a.csv"}]})
    resp = client.post("/api/v1/ios/train", json={"files": ["a.csv", "ghost.csv"]})
    assert resp.status_code == 400
    assert "ghost.csv" in resp.json()["detail"]


def test_train_409_when_already_running(client):
    busy = MagicMock()
    busy.poll.return_value = None  # 아직 실행 중
    train_mod._running["ios"] = {"process": busy}

    resp = client.post("/api/v1/ios/train", json={"files": ["a.csv"]})
    assert resp.status_code == 409


def test_train_202_spawns_worker(client, monkeypatch):
    monkeypatch.setattr(train_mod, "get_index", lambda p: {"files": [{"filename": "a.csv"}]})
    monkeypatch.setattr(train_mod, "next_version", lambda p: "v1.4")
    monkeypatch.setattr(train_mod, "mlflow", _fake_mlflow(run_id="run-xyz"))

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    spawned = {}

    def fake_popen(args, **kwargs):
        spawned["args"] = args
        return fake_proc

    monkeypatch.setattr(train_mod, "subprocess", SimpleNamespace(Popen=fake_popen))

    resp = client.post("/api/v1/ios/train", json={"files": ["a.csv"], "epochs": 50, "lr": 0.01})
    assert resp.status_code == 202

    data = resp.json()["data"]
    assert data["jobId"] == "run-xyz"
    assert data["version"] == "v1.4"
    assert data["totalEpochs"] == 50

    # 워커가 올바른 인자로 spawn 됐는지
    assert "app.worker.trainer" in spawned["args"]
    assert "--platform" in spawned["args"] and "ios" in spawned["args"]
    # 상태 저장
    assert train_mod._running["ios"]["job_id"] == "run-xyz"


def test_train_uses_default_epochs_and_lr(client, monkeypatch):
    monkeypatch.setattr(train_mod, "get_index", lambda p: {"files": [{"filename": "a.csv"}]})
    monkeypatch.setattr(train_mod, "next_version", lambda p: "v1.0")
    monkeypatch.setattr(train_mod, "mlflow", _fake_mlflow())
    proc = MagicMock(); proc.poll.return_value = None
    monkeypatch.setattr(train_mod, "subprocess", SimpleNamespace(Popen=lambda *a, **k: proc))

    resp = client.post("/api/v1/ios/train", json={"files": ["a.csv"]})
    assert resp.status_code == 202
    assert resp.json()["data"]["totalEpochs"] == 200  # 기본값


def test_train_status_maps_running(client, monkeypatch):
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

    resp = client.get("/api/v1/ios/train/status?jobId=run-xyz")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "running"
    assert data["epoch"] == 12
    assert data["totalEpochs"] == 100
    assert data["valAccuracy"] == 0.8


def test_train_status_404_on_unknown_job(client, monkeypatch):
    fake_client = MagicMock()
    fake_client.get_run.side_effect = Exception("not found")
    monkeypatch.setattr(
        train_mod, "mlflow",
        SimpleNamespace(set_tracking_uri=lambda u: None, MlflowClient=lambda: fake_client),
    )
    resp = client.get("/api/v1/ios/train/status?jobId=missing")
    assert resp.status_code == 404
