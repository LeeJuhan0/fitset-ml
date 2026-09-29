from datetime import datetime, timezone

from app.core import db
from app.core.config import settings
from app.deployment.repository import add_deployment

def _seed(*rows):
    async def go():
        async with db.session() as s:
            for platform, env, fields in rows:
                await add_deployment(s, platform, env, **fields)
    db.run(go())


def _at(day: int) -> datetime:
    return datetime(2026, 9, day, tzinfo=timezone.utc)


def test_internal_latest_per_kind_and_class(client, fresh_db):
    cls = dict(kind="classifier", bucket="fitset-models")
    phase = dict(kind="phase", bucket="fitset-phase-models")
    _seed(
        ("ios", "prod", dict(cls, version="v1.2", model_key="ios/v1.2/FitSet.mlpackage.zip", created_at=_at(1))),
        ("ios", "prod", dict(cls, version="v1.1", model_key="ios/v1.1/FitSet.mlpackage.zip", created_at=_at(3))),
        ("ios", "prod", dict(phase, class_name="SQUAT", version="v1.0", model_key="sq/v1.0/m", meta_key="sq/v1.0/meta.json", created_at=_at(2))),
        ("ios", "prod", dict(phase, class_name="PUSHUP", version="v1.0", model_key="pu/v1.0/m", meta_key="pu/v1.0/meta.json", created_at=_at(1))),
        ("ios", "prod", dict(phase, class_name="PUSHUP", version="v1.1", model_key="pu/v1.1/m", meta_key="pu/v1.1/meta.json", created_at=_at(4))),
        ("android", "prod", dict(cls, version="v9.9", model_key="android/v9.9/FitSet.onnx", created_at=_at(5))),
    )

    resp = client.get("/api/v1/internal/ios/models/latest?env=prod")
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["env"] == "prod"
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


def test_internal_envs_are_isolated(client, fresh_db):
    cls = dict(kind="classifier", bucket="fitset-models")
    _seed(
        ("ios", "prod", dict(cls, version="v1.0", model_key="ios/v1.0/FitSet.mlpackage.zip", created_at=_at(1))),
        ("ios", "dev", dict(cls, version="v2.0", model_key="ios/v2.0/FitSet.mlpackage.zip", created_at=_at(2))),
        ("ios", "dev", dict(kind="phase", bucket="fitset-phase-models", class_name="SQUAT", version="v0.1", model_key="sq", created_at=_at(3))),
    )

    prod = client.get("/api/v1/internal/ios/models/latest?env=prod").json()["data"]
    dev = client.get("/api/v1/internal/ios/models/latest?env=dev").json()["data"]
    assert prod["classifier"]["latestVersion"] == "v1.0" and prod["phaseModels"] == []
    assert dev["classifier"]["latestVersion"] == "v2.0" and [p["class"] for p in dev["phaseModels"]] == ["SQUAT"]


def test_internal_requires_valid_env(client, fresh_db):
    assert client.get("/api/v1/internal/ios/models/latest").status_code == 400
    assert client.get("/api/v1/internal/ios/models/latest?env=stage").status_code == 400


def test_internal_empty_when_never_deployed(client, fresh_db):
    data = client.get("/api/v1/internal/android/models/latest?env=prod").json()["data"]
    assert data == {"env": "prod", "classifier": None, "phaseModels": []}


def test_admin_deployed_matches_internal(admin_client, fresh_db):
    _seed(("ios", "dev", dict(kind="classifier", bucket="fitset-models", version="v3.0", model_key="k", created_at=_at(1))))
    admin = admin_client.get("/api/v1/ios/models/deployed?env=dev").json()["data"]
    internal = admin_client.get("/api/v1/internal/ios/models/latest?env=dev").json()["data"]
    assert admin == internal and admin["classifier"]["latestVersion"] == "v3.0"
