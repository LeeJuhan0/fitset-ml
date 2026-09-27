from datetime import datetime, timezone

from app.core import db
from app.core.config import settings
from app.deployment.models import ModelDeployment
from app.deployment.repository import add_deployment

def _seed(*rows):
    async def go():
        async with db.session() as s:
            for platform, fields in rows:
                await add_deployment(s, platform, **fields)
    db.run(go())


def _at(day: int) -> datetime:
    return datetime(2026, 9, day, tzinfo=timezone.utc)


def test_internal_latest_per_kind_and_class(client, fresh_db):
    cls = dict(kind="classifier", bucket="fitset-models")
    phase = dict(kind="phase", bucket="fitset-phase-models")
    _seed(
        ("ios", dict(cls, version="v1.2", model_key="ios/v1.2/FitSet.mlpackage.zip", created_at=_at(1))),
        ("ios", dict(cls, version="v1.1", model_key="ios/v1.1/FitSet.mlpackage.zip", created_at=_at(3))),
        ("ios", dict(phase, class_name="SQUAT", version="v1.0", model_key="sq/v1.0/m", meta_key="sq/v1.0/meta.json", created_at=_at(2))),
        ("ios", dict(phase, class_name="PUSHUP", version="v1.0", model_key="pu/v1.0/m", meta_key="pu/v1.0/meta.json", created_at=_at(1))),
        ("ios", dict(phase, class_name="PUSHUP", version="v1.1", model_key="pu/v1.1/m", meta_key="pu/v1.1/meta.json", created_at=_at(4))),
        ("android", dict(cls, version="v9.9", model_key="android/v9.9/FitSet.onnx", created_at=_at(5))),
    )

    resp = client.get("/api/v1/internal/ios/models/latest")
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["classifier"]["latestVersion"] == "v1.1"
    assert data["classifier"]["modelUrl"] == "ios/v1.1/FitSet.mlpackage.zip"
    assert data["classifier"]["metaUrl"] == settings.class_mapping_url
    assert data["classifier"]["updatedAt"].startswith("2026-09-03")
    assert "class" not in data["classifier"]

    phases = {p["class"]: p for p in data["phaseModels"]}
    assert list(phases) == ["PUSHUP", "SQUAT"]
    assert phases["PUSHUP"]["latestVersion"] == "v1.1"
    assert phases["PUSHUP"]["metaUrl"] == "pu/v1.1/meta.json"
    assert phases["SQUAT"]["modelUrl"] == "sq/v1.0/m"


def test_internal_empty_when_never_deployed(client, fresh_db):
    data = client.get("/api/v1/internal/android/models/latest").json()["data"]
    assert data == {"classifier": None, "phaseModels": []}


def test_classifier_deploy_writes_history(admin_client, monkeypatch, fresh_db):
    import sys
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import app.deployment.service as deploy_mod

    fake = MagicMock()
    fake.get_experiment_by_name.return_value = SimpleNamespace(experiment_id="e")
    fake.search_runs.return_value = [SimpleNamespace(info=SimpleNamespace(run_id="r"))]
    monkeypatch.setitem(sys.modules, "mlflow", SimpleNamespace(set_tracking_uri=lambda u: None, MlflowClient=lambda: fake))
    monkeypatch.setattr(deploy_mod, "put_latest", lambda p, d: None)

    assert admin_client.post("/api/v1/android/deploy", json={"version": "v2.0"}).status_code == 200

    async def rows():
        async with db.session() as s:
            return (await s.exec(__import__("sqlmodel").select(ModelDeployment))).all()
    [row] = db.run(rows())
    assert (row.kind, row.version, row.bucket, row.model_key) == ("classifier", "v2.0", "fitset-models", "android/v2.0/FitSet.onnx")
