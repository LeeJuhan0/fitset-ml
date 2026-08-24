"""어드민 Basic 인증(core.security) — /api/admin/* 전 엔드포인트 공통 규칙.

인증 없음·불일치는 401, 계정 미설정은 503 잠금(fail closed).
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from tests.conftest import ADMIN_AUTH

ADMIN_PATHS = [
    ("get", "/api/admin/v1/ios/data"),
    ("get", "/api/admin/v1/ios/runs"),
    ("post", "/api/admin/v1/ios/deploy"),
    ("get", "/api/admin/v1/ios/model/version-stats"),
]


@pytest.mark.parametrize("method,path", ADMIN_PATHS)
def test_no_credentials_rejected_401(admin_client, method, path):
    bare = TestClient(app)   # 계정은 설정돼 있고(admin_client 픽스처) 인증 헤더만 없음
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
    # 계정이 비어 있으면 맞는 비밀번호가 존재하지 않으므로 전면 잠금
    monkeypatch.setattr(settings, "mlflow_ui_user", "")
    monkeypatch.setattr(settings, "mlflow_ui_password", "")
    resp = client.get("/api/admin/v1/ios/data", auth=("any", "any"))
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "ADMIN_AUTH_LOCKED"


def test_user_endpoints_do_not_require_basic(user_client, monkeypatch):
    # 유저 경로는 Basic 의존성이 없어야 한다 — 어드민 잠금과 무관하게 JWT만으로 동작
    import app.deployment.service as model_mod
    monkeypatch.setattr(settings, "mlflow_ui_user", "")
    monkeypatch.setattr(settings, "mlflow_ui_password", "")
    monkeypatch.setattr(model_mod, "get_latest", lambda p: None)
    resp = user_client.get("/api/v1/ios/model/latest")
    assert resp.status_code == 404   # 503/401이 아니라 도메인 결과(배포 없음)


# ── 정적 대시보드("/" 마운트) Basic 보호 — static_basic_auth_middleware ──

def test_static_dashboard_requires_basic(admin_client):
    bare = TestClient(app)   # 계정은 설정돼 있고 인증 헤더만 없음
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
    # 배포 헬스체크는 인증·계정 설정과 무관하게 열려 있어야 한다(ELB가 무인증 호출)
    monkeypatch.setattr(settings, "mlflow_ui_user", "")
    monkeypatch.setattr(settings, "mlflow_ui_password", "")
    resp = client.get("/api/health")
    assert resp.status_code == 200
