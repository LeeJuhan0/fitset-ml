import base64
import secrets

from fastapi import Depends, FastAPI, Request, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.core.config import settings
from app.core.exception_register import error_response
from app.core.exceptions import AdminAuthLockedError, UnauthorizedError

basic_scheme = HTTPBasic()


def check_basic_auth(credentials: HTTPBasicCredentials = Depends(basic_scheme)) -> None:
    """Basic 자격 검증, 미설정 503, 불일치 401"""
    if not settings.mlflow_ui_user or not settings.mlflow_ui_password:
        raise AdminAuthLockedError()
    user_ok = secrets.compare_digest(credentials.username.encode(), settings.mlflow_ui_user.encode())
    password_ok = secrets.compare_digest(credentials.password.encode(), settings.mlflow_ui_password.encode())
    if user_ok and password_ok:
        return
    raise UnauthorizedError()


def credentials_configured() -> bool:
    """관리자 계정 설정 여부"""
    return bool(settings.mlflow_ui_user and settings.mlflow_ui_password)


def basic_header_valid(header: str) -> bool:
    """Authorization Basic 헤더 검증"""
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


_STATIC_AUTH_EXEMPT_PREFIXES = ("/api/", "/mlflow", "/docs", "/openapi.json", "/redoc")


def register_static_basic_guard(app: FastAPI) -> None:
    """정적 대시보드("/")에 Basic 요구, API·문서·프록시 경로는 제외"""

    @app.middleware("http")
    async def static_basic_auth_middleware(request: Request, call_next) -> Response:
        """정적 경로 Basic 검사, 제외 경로 통과"""
        if request.url.path.startswith(_STATIC_AUTH_EXEMPT_PREFIXES):
            return await call_next(request)
        if not credentials_configured():
            return error_response(request, 503, "ADMIN_AUTH_LOCKED", "관리자 자격증명이 설정되지 않았습니다.")
        if not basic_header_valid(request.headers.get("Authorization", "")):
            return error_response(
                request, 401, "UNAUTHORIZED", "관리자 인증에 실패했습니다.",
                extra_headers={"WWW-Authenticate": 'Basic realm="FitSet Admin"'},
            )
        return await call_next(request)
