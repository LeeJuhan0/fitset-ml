# ─────────────────────────────────────────────────────────────────────────────
# 유저 JWT 검증(app/core/auth) 단위 테스트.
# 실제 JWKS에 붙지 않도록 settings.jwt_public_key_pem에 테스트용 공개키를 주입하고,
# 대응 개인키로 서명한 토큰을 만들어 서명·exp·sub 검증 규칙을 확인한다.
# ─────────────────────────────────────────────────────────────────────────────
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app.core import auth
from app.core.config import settings


def _make_keypair():
    # 테스트 전용 RSA 키쌍 — (개인키 PEM: 서명용, 공개키 PEM: 검증용)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


PRIVATE_PEM, PUBLIC_PEM = _make_keypair()
OTHER_PRIVATE_PEM, _ = _make_keypair()   # 다른 키로 서명된(위조) 토큰용


def _token(private_pem: str = PRIVATE_PEM, **claims) -> str:
    # 기본은 유효한 클레임(sub + 미래 exp) — 테스트가 claims로 덮어써 실패 케이스를 만든다
    payload = {"sub": "user-1", "exp": int(time.time()) + 3600, **claims}
    payload = {k: v for k, v in payload.items() if v is not None}   # None = 클레임 제거
    return jwt.encode(payload, private_pem, algorithm="RS256")


@pytest.fixture(autouse=True)
def inject_public_key(monkeypatch):
    # 모든 테스트에서 JWKS 조회를 우회하고 테스트 공개키로 검증한다
    monkeypatch.setattr(settings, "jwt_public_key_pem", PUBLIC_PEM)


def test_valid_token_returns_user_id():
    assert auth.verify_token(_token(sub="user-42")) == "user-42"


def test_expired_token_rejected():
    with pytest.raises(HTTPException) as exc:
        auth.verify_token(_token(exp=int(time.time()) - 10))
    assert exc.value.status_code == 401


def test_wrong_signature_rejected():
    # 다른 개인키로 서명 — 우리 공개키로 검증 실패해야 한다
    with pytest.raises(HTTPException) as exc:
        auth.verify_token(_token(private_pem=OTHER_PRIVATE_PEM))
    assert exc.value.status_code == 401


def test_missing_sub_rejected():
    with pytest.raises(HTTPException) as exc:
        auth.verify_token(_token(sub=None))
    assert exc.value.status_code == 401


def test_missing_exp_rejected():
    with pytest.raises(HTTPException) as exc:
        auth.verify_token(_token(exp=None))
    assert exc.value.status_code == 401


def test_garbage_token_rejected():
    with pytest.raises(HTTPException) as exc:
        auth.verify_token("not-a-jwt")
    assert exc.value.status_code == 401


def test_hs256_alg_confusion_rejected():
    # 공개키를 HMAC 시크릿으로 쓰는 알고리즘 혼동 공격 — RS256만 허용하므로 거부.
    # PyJWT는 PEM으로 HS256 인코딩 자체를 막아주므로 공격 토큰은 수동으로 조립한다.
    import base64, hashlib, hmac, json

    def _b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({"sub": "user-1", "exp": int(time.time()) + 3600}).encode())
    sig = _b64(hmac.new(PUBLIC_PEM.encode(), header + b"." + payload, hashlib.sha256).digest())
    forged = b".".join([header, payload, sig]).decode()
    with pytest.raises(HTTPException) as exc:
        auth.verify_token(forged)
    assert exc.value.status_code == 401
