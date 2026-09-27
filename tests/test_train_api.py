from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from conftest import async_
from app.core import db
from app.core import utils
from app.training.repository import add_training_run, get_training_run
import app.training.service as train_mod


@pytest.fixture(autouse=True)
def reset_procs(fresh_db):
    train_mod._procs.clear()
    yield
    train_mod._procs.clear()


def _fake_mlflow(run_id="run-xyz", status="RUNNING", metrics=None, tags=None):
    fake_client = MagicMock()
    fake_client.get_experiment_by_name.return_value = SimpleNamespace(experiment_id="exp-1")
    fake_client.create_run.return_value = SimpleNamespace(info=SimpleNamespace(run_id=run_id))
    fake_client.get_run.return_value = SimpleNamespace(
        info=SimpleNamespace(status=status, experiment_id="exp-1"),
        data=SimpleNamespace(metrics=metrics or {}, tags=tags or {}),
    )
    fake = SimpleNamespace(set_tracking_uri=lambda uri: None, MlflowClient=lambda: fake_client)
    return fake, fake_client


def _seed_running(run_id="run-xyz", version="v1.4", platform="ios"):
    async def go():
        async with db.session() as s:
            await add_training_run(s, platform, mlflow_run_id=run_id, version=version, epochs=100, lr=0.001, num_files=1)
    db.run(go())


def _row(run_id="run-xyz"):
    async def go():
        async with db.session() as s:
            return await get_training_run(s, run_id)
    return db.run(go())


def _proc(returncode):
    p = MagicMock()
    p.poll.return_value = returncode
    p.returncode = returncode
    return p


def test_train_400_on_unknown_file(admin_client, monkeypatch):
    monkeypatch.setattr(train_mod, "uploaded_filenames", async_(lambda s, p: {"a.csv"}))
    resp = admin_client.post("/api/v1/ios/train", json={"files": ["a.csv", "ghost.csv"]})
    assert resp.status_code == 400
    assert "ghost.csv" in resp.json()["error"]["message"]


def test_train_409_when_already_running(admin_client):
    _seed_running()
    train_mod._procs["run-xyz"] = _proc(None)

    resp = admin_client.post("/api/v1/ios/train", json={"files": ["a.csv"]})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CONFLICT"
    assert resp.headers["X-Trace-Id"] == resp.json()["traceId"]


def test_train_202_spawns_worker_and_records_run(admin_client, monkeypatch):
    monkeypatch.setattr(train_mod, "uploaded_filenames", async_(lambda s, p: {"a.csv"}))
    monkeypatch.setattr(train_mod, "next_version", lambda p: "v1.4")
    monkeypatch.setattr(train_mod, "mlflow", _fake_mlflow(run_id="run-xyz")[0])
    spawned = {}

    def fake_popen(args, **kwargs):
        spawned["args"] = args
        return _proc(None)

    monkeypatch.setattr(train_mod, "subprocess", SimpleNamespace(Popen=fake_popen))

    resp = admin_client.post("/api/v1/ios/train", json={"files": ["a.csv"], "epochs": 50, "lr": 0.01})
    assert resp.status_code == 202
    data = resp.json()["data"]
    assert (data["jobId"], data["version"], data["totalEpochs"]) == ("run-xyz", "v1.4", 50)
    assert "app.worker.trainer" in spawned["args"] and "ios" in spawned["args"]
    assert "run-xyz" in train_mod._procs
    row = _row()
    assert (row.status, row.epochs, row.num_files) == ("running", 50, 1)


def test_train_status_maps_running(admin_client, monkeypatch):
    _seed_running()
    train_mod._procs["run-xyz"] = _proc(None)
    fake, _ = _fake_mlflow(metrics={"epoch": 12, "train_loss": 0.4, "val_loss": 0.5, "val_accuracy": 0.8})
    monkeypatch.setattr(train_mod, "mlflow", fake)

    data = admin_client.get("/api/v1/ios/train/status?jobId=run-xyz").json()["data"]
    assert (data["status"], data["epoch"], data["totalEpochs"], data["valAccuracy"]) == ("running", 12, 100, 0.8)
    assert data["error"] is None


def test_oom_killed_process_marked_failed(admin_client, monkeypatch, tmp_path):
    _seed_running()
    train_mod._procs["run-xyz"] = _proc(-9)
    monkeypatch.setattr(train_mod, "_log_path", lambda p, v: tmp_path / "none.log")
    fake, client = _fake_mlflow()
    monkeypatch.setattr(train_mod, "mlflow", fake)

    data = admin_client.get("/api/v1/ios/train/status?jobId=run-xyz").json()["data"]
    assert "OOM" in data["error"]
    row = _row()
    assert row.status == "failed" and "SIGKILL" in row.error and row.finished_at is not None
    client.set_terminated.assert_called_once_with("run-xyz", status="FAILED")
    assert "run-xyz" not in train_mod._procs


def test_lost_process_after_restart_marked_failed(admin_client, monkeypatch):
    _seed_running()
    fake, client = _fake_mlflow()
    monkeypatch.setattr(train_mod, "mlflow", fake)

    data = admin_client.get("/api/v1/ios/train/status?jobId=run-xyz").json()["data"]
    assert data["error"] == utils.LOST_PROCESS_ERROR
    row = _row()
    assert row.status == "failed" and row.error == utils.LOST_PROCESS_ERROR
    client.set_terminated.assert_called_once()


def test_clean_exit_marked_completed(admin_client, monkeypatch):
    _seed_running()
    train_mod._procs["run-xyz"] = _proc(0)
    fake, client = _fake_mlflow(status="FINISHED")
    monkeypatch.setattr(train_mod, "mlflow", fake)

    admin_client.get("/api/v1/ios/train/status?jobId=run-xyz")
    row = _row()
    assert row.status == "completed" and row.error is None
    client.set_terminated.assert_not_called()


def test_exit_error_messages():
    assert "OOM" in utils.exit_error(-9, "")
    assert "SIGTERM" in utils.exit_error(-15, "")
    assert utils.exit_error(1, "Traceback\nValueError: x\n").endswith("ValueError: x")


def test_train_status_404_on_unknown_job(admin_client, monkeypatch):
    fake, client = _fake_mlflow()
    client.get_run.side_effect = Exception("not found")
    monkeypatch.setattr(train_mod, "mlflow", fake)
    assert admin_client.get("/api/v1/ios/train/status?jobId=missing").status_code == 404
