"""MLflow run 목록/메트릭 히스토리 API (app.training) — MLflow 가짜 대체."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.training.service as runs_mod


def _run(run_id, name, status, val_acc, start=1000, end=4000):
    return SimpleNamespace(
        info=SimpleNamespace(
            run_id=run_id, run_name=name, status=status,
            start_time=start, end_time=end,
        ),
        data=SimpleNamespace(
            params={"epochs": "100", "lr": "0.001", "files": '["a.csv", "b.csv"]'},
            metrics={
                "train_loss": 0.2, "val_loss": 0.3, "val_accuracy": val_acc,
                "test_accuracy": 0.88, "f1_macro": 0.9, "epoch": 100,
            },
        ),
    )


def _install(monkeypatch, experiment, search_results=None, history=None):
    fake_client = MagicMock()
    fake_client.get_experiment_by_name.return_value = experiment
    if search_results is not None:
        fake_client.search_runs.return_value = search_results
    if history is not None:
        fake_client.get_metric_history.return_value = history
    monkeypatch.setattr(
        runs_mod, "mlflow",
        SimpleNamespace(set_tracking_uri=lambda u: None, MlflowClient=lambda: fake_client),
    )
    return fake_client


def test_runs_empty_when_no_experiment(client, monkeypatch):
    _install(monkeypatch, experiment=None)
    resp = client.get("/api/v1/ios/runs")
    assert resp.status_code == 200
    assert resp.json()["data"]["runs"] == []


def test_runs_lists_and_picks_best(client, monkeypatch):
    exp = SimpleNamespace(experiment_id="exp-1")
    runs = [
        _run("run-1", "v1.0", "FINISHED", val_acc=0.80),
        _run("run-2", "v1.1", "FINISHED", val_acc=0.92),  # best
        _run("run-3", "v1.2", "RUNNING", val_acc=0.99),   # 미완료 → 제외
    ]
    _install(monkeypatch, experiment=exp, search_results=runs)

    data = client.get("/api/v1/ios/runs").json()["data"]
    assert len(data["runs"]) == 3
    assert data["bestRunId"] == "run-2"

    first = data["runs"][0]
    assert first["params"]["numFiles"] == 2  # files 길이 파싱
    assert first["params"]["epochs"] == 100
    assert first["duration"] == 3  # (4000-1000)/1000


def test_runs_metric_history(client, monkeypatch):
    history = [SimpleNamespace(step=i, value=0.5 - i * 0.1) for i in range(3)]
    _install(monkeypatch, experiment=SimpleNamespace(experiment_id="e"), history=history)

    data = client.get("/api/v1/ios/runs/run-1/history?metric=val_loss").json()["data"]
    assert data["metric"] == "val_loss"
    assert [h["step"] for h in data["history"]] == [0, 1, 2]
    assert [h["value"] for h in data["history"]] == pytest.approx([0.5, 0.4, 0.3])
