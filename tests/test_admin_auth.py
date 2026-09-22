import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from tests.conftest import ADMIN_AUTH

ADMIN_PATHS = [
    ("get", "/api/v1/ios/data"),
    ("get", "/api/v1/ios/runs"),
    ("post", "/api/v1/ios/deploy"),
    ("get", "/api/v1/ios/model/version-stats"),
]


@pytest.mark.parametrize("method,path", ADMIN_PATHS)
def test_no_credentials_rejected_401(admin_client, method, path):
    bare = TestClient(app)
    resp = getattr(bare, method)(path)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize("method,path", ADMIN_PATHS)
def test_wrong_password_rejected_401(admin_client, method, path):
    bad = TestClient(app)
    bad.auth = (ADMIN_AUTH[0], "wrong-password")
    resp = getattr(bad, method)(path)
    assert resp.status_code == 401
    assert "Basic" in resp.headers.get("www-authenticate", "")


def test_unset_credentials_lock_503(client, monkeypatch):
    monkeypatch.setattr(settings, "mlflow_ui_user", "")
    monkeypatch.setattr(settings, "mlflow_ui_password", "")
    resp = client.get("/api/v1/ios/data", auth=("any", "any"))
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "ADMIN_AUTH_LOCKED"


def test_static_dashboard_requires_basic(admin_client):
    bare = TestClient(app)
    resp = bare.get("/")
    assert resp.status_code == 401
    assert "Basic" in resp.headers.get("www-authenticate", "")


def test_static_dashboard_serves_with_basic(admin_client):
    resp = admin_client.get("/")
    assert resp.status_code == 200
    assert "FitSet ML" in resp.text


def test_static_locked_503_when_unset(client, monkeypatch):
    monkeypatch.setattr(settings, "mlflow_ui_user", "")
    monkeypatch.setattr(settings, "mlflow_ui_password", "")
    resp = client.get("/")
    assert resp.status_code == 503


def test_health_open_without_auth(client, monkeypatch):
    monkeypatch.setattr(settings, "mlflow_ui_user", "")
    monkeypatch.setattr(settings, "mlflow_ui_password", "")
    resp = client.get("/api/health")
    assert resp.status_code == 200
