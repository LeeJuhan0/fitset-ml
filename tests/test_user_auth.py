# ─────────────────────────────────────────────────────────────────────────────
# 유저 JWT 인증 — /api/v1 전 엔드포인트 공통 규칙(엔드포인트 레벨).
# 토큰 검증 자체의 단위 테스트는 test_auth.py, 여기는 라우터 부착 여부를 본다.
# ─────────────────────────────────────────────────────────────────────────────
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from user_api.main import app
from tests.conftest import USER_PUBLIC_PEM, make_user_token

USER_PATHS = [
    ("get", "/ml/v1/ios/data/presigned-url?class=SQUAT&deviceId=ABC12345"),
    ("post", "/ml/v1/ios/data/upload-confirm"),
    ("get", "/ml/v1/ios/model/latest"),
]


@pytest.fixture(autouse=True)
def inject_public_key(monkeypatch):
    monkeypatch.setattr(settings, "jwt_public_key_pem", USER_PUBLIC_PEM)


@pytest.mark.parametrize("method,path", USER_PATHS)
def test_no_token_rejected_401(method, path):
    bare = TestClient(app)
    resp = getattr(bare, method)(path)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize("method,path", USER_PATHS)
def test_expired_token_rejected_401(method, path):
    stale = TestClient(app)
    stale.headers["Authorization"] = f"Bearer {make_user_token(ttl=-10)}"
    resp = getattr(stale, method)(path)
    assert resp.status_code == 401


def test_basic_credentials_do_not_pass_user_endpoints():
    # 어드민 Basic 크리덴셜은 유저 경로(JWT)를 통과할 수 없다 — 계층 혼용 차단
    basic = TestClient(app)
    basic.auth = ("admin", "admin-test-pw")
    resp = basic.get("/ml/v1/ios/model/latest")
    assert resp.status_code == 401
