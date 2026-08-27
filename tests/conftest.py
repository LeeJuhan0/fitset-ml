"""공통 픽스처.

ML 서버는 S3(boto3)와 MLflow에 의존한다. 단위/통합 테스트에서는 실제 AWS·MLflow에
붙지 않도록, 각 도메인 service 네임스페이스로 import된 의존 함수를 테스트마다 monkeypatch 한다.
(예: app.data.service 는 `from app.data.repository import get_index` 하므로 app.data.service.get_index 를 패치)
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.core.config import settings
from admin_api.main import app as admin_app   # 어드민 라우터·대시보드·mlflow 프록시
from user_api.main import app as user_app     # 유저 라우터 3개(JWT)

# 유저 JWT 테스트 키쌍 — 개인키로 서명하고 공개키를 settings에 주입해 JWKS를 우회한다
_USER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
USER_PRIVATE_PEM = _USER_KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
USER_PUBLIC_PEM = _USER_KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()


def make_user_token(user_id: str = "user-1", ttl: int = 3600) -> str:
    # 백엔드 access 토큰과 같은 형태(RS256, sub·exp)의 테스트 토큰
    return jwt.encode(
        {"sub": user_id, "exp": int(time.time()) + ttl}, USER_PRIVATE_PEM, algorithm="RS256"
    )

# 어드민 Basic 공용 계정(테스트용) — check_basic_auth가 settings와 대조한다
ADMIN_AUTH = ("admin", "admin-test-pw")


@pytest.fixture
def client():
    # 무인증 클라이언트 — 어드민 서비스 대상(정적·헬스·인증 실패 케이스 검증용)
    return TestClient(admin_app)


@pytest.fixture
def admin_client(monkeypatch):
    # 어드민 계정을 설정에 주입하고, 모든 요청에 Basic 인증이 실리는 클라이언트를 돌려준다
    monkeypatch.setattr(settings, "mlflow_ui_user", ADMIN_AUTH[0])
    monkeypatch.setattr(settings, "mlflow_ui_password", ADMIN_AUTH[1])
    c = TestClient(admin_app)
    c.auth = ADMIN_AUTH
    return c


@pytest.fixture
def user_client(monkeypatch):
    # 유효한 Bearer 토큰이 모든 요청에 실리는 클라이언트 — 유저 엔드포인트(/api/v1) 테스트용
    monkeypatch.setattr(settings, "jwt_public_key_pem", USER_PUBLIC_PEM)
    c = TestClient(user_app)
    c.headers["Authorization"] = f"Bearer {make_user_token()}"
    return c
