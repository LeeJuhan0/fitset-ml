# ─────────────────────────────────────────────────────────────────────────────
# 어드민 Basic 인증 — 어드민 라우터(/api/admin/*)와 MLflow UI 프록시(/mlflow/*)가 공유.
# 계정은 환경변수 하나(mlflow_ui_user/password) — 팀 내부 공용 콘솔 계정.
# 유저 트래픽(JWT, app/core/auth.py)과 달리 매 요청 헤더의 아이디·비밀번호를 그대로 대조한다.
# ─────────────────────────────────────────────────────────────────────────────
import base64    # 미들웨어에서 Basic 헤더 직접 해석용 (Depends를 못 쓰는 지점)
import secrets   # compare_digest — 문자열 비교 시간차로 비밀번호를 추측하는 타이밍 공격 방지

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.core.config import settings

basic_scheme = HTTPBasic()   # Authorization: Basic 헤더 파싱, 없으면 401 + 브라우저 로그인창


def check_basic_auth(credentials: HTTPBasicCredentials = Depends(basic_scheme)) -> None:
    # 자격 미설정이면 잠금(fail closed), 불일치면 401로 재입력 유도
    if not settings.mlflow_ui_user or not settings.mlflow_ui_password:
        raise HTTPException(
            status_code=503,
            detail={"code": "ADMIN_AUTH_LOCKED", "message": "관리자 자격증명이 설정되지 않았습니다."},
        )
    user_ok = secrets.compare_digest(credentials.username.encode(), settings.mlflow_ui_user.encode())
    password_ok = secrets.compare_digest(credentials.password.encode(), settings.mlflow_ui_password.encode())
    if user_ok and password_ok:
        return
    raise HTTPException(
        status_code=401,
        detail={"code": "UNAUTHORIZED", "message": "관리자 인증에 실패했습니다."},
        headers={"WWW-Authenticate": 'Basic realm="FitSet Admin"'},
    )


def credentials_configured() -> bool:
    # 어드민 계정 설정 여부 — 미설정이면 전 계층 fail closed
    return bool(settings.mlflow_ui_user and settings.mlflow_ui_password)


def basic_header_valid(header: str) -> bool:
    """Authorization 헤더 문자열을 직접 검사한다 — 정적 파일 미들웨어용(Depends 불가 지점).

    검사 규칙은 check_basic_auth와 동일: 계정 미설정이면 무조건 실패(fail closed).
    """
    if not credentials_configured():
        return False
    if not header.startswith("Basic "):
        return False
    try:
        user, _, password = base64.b64decode(header[6:]).decode().partition(":")
    except Exception:
        return False
    user_ok = secrets.compare_digest(user.encode(), settings.mlflow_ui_user.encode())
    password_ok = secrets.compare_digest(password.encode(), settings.mlflow_ui_password.encode())
    return user_ok and password_ok
