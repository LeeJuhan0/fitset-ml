"""모델 배포 라우터 (app.api.deploy) — MLflow·S3 의존은 가짜로 대체.

배포는 MLflow run 존재 확인 → latest.json 업데이트. 플랫폼별 모델 확장자
(ios=.mlpackage / android=.tflite)가 올바른지 검증한다."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.api.deploy as deploy_mod


def _install_fake_mlflow(monkeypatch, experiment, runs):
    """experiment=None 이면 실험 없음, runs=[] 이면 해당 버전 run 없음."""
    fake_client = MagicMock()
    fake_client.get_experiment_by_name.return_value = experiment
    fake_client.search_runs.return_value = runs

    fake_mlflow = SimpleNamespace(
        set_tracking_uri=lambda uri: None,
        MlflowClient=lambda: fake_client,
    )
    monkeypatch.setattr(deploy_mod, "mlflow", fake_mlflow)
    return fake_client


def test_deploy_404_when_no_experiment(client, monkeypatch):
    _install_fake_mlflow(monkeypatch, experiment=None, runs=[])
    resp = client.post("/api/v1/ios/deploy", json={"version": "v1.3"})
    assert resp.status_code == 404


def test_deploy_404_when_version_run_missing(client, monkeypatch):
    exp = SimpleNamespace(experiment_id="exp-1")
    _install_fake_mlflow(monkeypatch, experiment=exp, runs=[])
    resp = client.post("/api/v1/ios/deploy", json={"version": "v9.9"})
    assert resp.status_code == 404


@pytest.mark.parametrize("platform,ext", [("ios", "mlpackage"), ("android", "tflite")])
def test_deploy_success_updates_latest(client, monkeypatch, platform, ext):
    exp = SimpleNamespace(experiment_id="exp-1")
    run = SimpleNamespace(info=SimpleNamespace(run_id="run-abc"))
    _install_fake_mlflow(monkeypatch, experiment=exp, runs=[run])

    saved = {}
    monkeypatch.setattr(deploy_mod, "put_latest", lambda p, d: saved.update(platform=p, data=d))

    resp = client.post(f"/api/v1/{platform}/deploy", json={"version": "v1.3"})
    assert resp.status_code == 200

    body = resp.json()["data"]
    assert body["deployedVersion"] == "v1.3"
    assert body["platform"] == platform

    # latest.json 내용 검증
    assert saved["platform"] == platform
    assert saved["data"]["version"] == "v1.3"
    assert saved["data"]["mlflowRunId"] == "run-abc"
    assert saved["data"]["modelUrl"].endswith(f"/{platform}/v1.3/FitSet.{ext}")


def test_deploy_requires_version_field(client, monkeypatch):
    _install_fake_mlflow(monkeypatch, experiment=None, runs=[])
    resp = client.post("/api/v1/ios/deploy", json={})  # version 누락
    assert resp.status_code == 422  # Pydantic 검증 실패
