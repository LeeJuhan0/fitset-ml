"""학습 시작/진행률 API (app.training) — MLflow·subprocess·S3 가짜 대체.

학습 워커 spawn(subprocess)과 MLflow run 생성은 부수효과이므로 모두 가짜로 막고,
입력 검증(존재하지 않는 파일 400, 중복 학습 409)과 상태 매핑만 검증한다.
패치 대상은 유스케이스가 사는 service 네임스페이스."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

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
    monkeypatch.setattr(train_mod, "get_index", lambda p: {"files": [{"filename": "a.csv"}]})
    resp = admin_client.post("/api/admin/v1/ios/train", json={"files": ["a.csv", "ghost.csv"]})
    assert resp.status_code == 400
    assert "ghost.csv" in resp.json()["error"]["message"]


def test_train_400_on_not_uploaded_file(admin_client, monkeypatch):
    # presigned URL만 받고 업로드를 안 끝낸 예약 엔트리 — S3에 실물이 없어 워커가 404로 죽는다.
    monkeypatch.setattr(train_mod, "get_index", lambda p: {"files": [
        {"filename": "a.csv", "uploaded": True},
        {"filename": "pending.csv", "uploaded": False},
    ]})
    resp = admin_client.post("/api/admin/v1/ios/train", json={"files": ["a.csv", "pending.csv"]})
    assert resp.status_code == 400
    assert "pending.csv" in resp.json()["error"]["message"]


def test_train_409_when_already_running(admin_client):
    busy = MagicMock()
    busy.poll.return_value = None  # 아직 실행 중
    train_mod._running["ios"] = {"process": busy}

    resp = admin_client.post("/api/admin/v1/ios/train", json={"files": ["a.csv"]})
    assert resp.status_code == 409
    # 비즈니스 충돌은 CONFLICT — 서버 오류(INTERNAL_ERROR)와 코드로 구분돼야 한다
    assert resp.json()["error"]["code"] == "CONFLICT"
    # 실패 응답도 X-Trace-Id 헤더 보장(핸들러가 직접 싣는다 — 500 경로 포함)
    assert resp.headers["X-Trace-Id"] == resp.json()["traceId"]


def test_train_202_spawns_worker(admin_client, monkeypatch):
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

    resp = admin_client.post("/api/admin/v1/ios/train", json={"files": ["a.csv"], "epochs": 50, "lr": 0.01})
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


def test_train_uses_default_epochs_and_lr(admin_client, monkeypatch):
    monkeypatch.setattr(train_mod, "get_index", lambda p: {"files": [{"filename": "a.csv"}]})
    monkeypatch.setattr(train_mod, "next_version", lambda p: "v1.0")
    monkeypatch.setattr(train_mod, "mlflow", _fake_mlflow())
    proc = MagicMock(); proc.poll.return_value = None
    monkeypatch.setattr(train_mod, "subprocess", SimpleNamespace(Popen=lambda *a, **k: proc))

    resp = admin_client.post("/api/admin/v1/ios/train", json={"files": ["a.csv"]})
    assert resp.status_code == 202
    assert resp.json()["data"]["totalEpochs"] == 200  # 기본값


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

    resp = admin_client.get("/api/admin/v1/ios/train/status?jobId=run-xyz")
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
    resp = admin_client.get("/api/admin/v1/ios/train/status?jobId=missing")
    assert resp.status_code == 404
