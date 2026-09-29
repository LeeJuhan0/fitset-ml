import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core import db
from app.deployment.models import ModelDeployment


def _install_fake_mlflow(monkeypatch, experiment, runs):
    """experiment=None 이면 실험 없음, runs=[] 이면 해당 버전 run 없음"""
    fake_client = MagicMock()
    fake_client.get_experiment_by_name.return_value = experiment
    fake_client.search_runs.return_value = runs

    fake_mlflow = SimpleNamespace(
        set_tracking_uri=lambda uri: None,
        MlflowClient=lambda: fake_client,
    )
    monkeypatch.setitem(sys.modules, "mlflow", fake_mlflow)
    return fake_client


def _rows():
    async def go():
        async with db.session() as s:
            return (await s.exec(__import__("sqlmodel").select(ModelDeployment))).all()
    return db.run(go())


def test_deploy_404_when_no_experiment(admin_client, monkeypatch):
    _install_fake_mlflow(monkeypatch, experiment=None, runs=[])
    resp = admin_client.post("/api/v1/ios/deploy", json={"version": "v1.3", "env": "dev"})
    assert resp.status_code == 404


def test_deploy_404_when_version_run_missing(admin_client, monkeypatch):
    exp = SimpleNamespace(experiment_id="exp-1")
    _install_fake_mlflow(monkeypatch, experiment=exp, runs=[])
    resp = admin_client.post("/api/v1/ios/deploy", json={"version": "v9.9", "env": "dev"})
    assert resp.status_code == 404


@pytest.mark.parametrize("platform,ext", [("ios", "mlpackage.zip"), ("android", "onnx")])
@pytest.mark.parametrize("env", ["dev", "prod"])
def test_deploy_success_writes_env_history(admin_client, monkeypatch, fresh_db, platform, ext, env):
    exp = SimpleNamespace(experiment_id="exp-1")
    run = SimpleNamespace(info=SimpleNamespace(run_id="run-abc"))
    _install_fake_mlflow(monkeypatch, experiment=exp, runs=[run])

    resp = admin_client.post(f"/api/v1/{platform}/deploy", json={"version": "v1.3", "env": env})
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert (body["deployedVersion"], body["platform"], body["env"]) == ("v1.3", platform, env)

    [row] = _rows()
    assert (row.kind, row.version, row.bucket, row.model_key) == ("classifier", "v1.3", "fitset-models", f"{platform}/v1.3/FitSet.{ext}")
    assert row.environment.name == env


@pytest.mark.parametrize("body", [{}, {"version": "v1.3"}, {"version": "v1.3", "env": "stage"}])
def test_deploy_requires_version_and_env(admin_client, monkeypatch, body):
    _install_fake_mlflow(monkeypatch, experiment=None, runs=[])
    resp = admin_client.post("/api/v1/ios/deploy", json=body)
    assert resp.status_code == 400
