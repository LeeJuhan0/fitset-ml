import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import TRACE_ID_HEADER
from app.core.schemas import ErrorResponse

logger = logging.getLogger("fitset-ml")

ERROR_DOC = {"default": {"model": ErrorResponse, "description": "실패 — {traceId, error: {code, message, details}}"}}

_DEFAULT_ERROR_CODES = {
    400: "INVALID_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
}
_FALLBACK_ERROR_CODE = "INTERNAL_ERROR"


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list | None = None,
    extra_headers: dict | None = None,
) -> JSONResponse:
    """실패 봉투 JSON, traceId 헤더 첨부"""
    trace_id = getattr(request.state, "trace_id", "")
    return JSONResponse(
        status_code=status_code,
        headers={TRACE_ID_HEADER: trace_id, **(extra_headers or {})},
        content={
            "traceId": trace_id,
            "error": {"code": code, "message": message, "details": details or []},
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """HTTPException, 요청 검증 실패, 미처리 예외 3종 등록"""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """HTTPException → 실패 봉투, dict detail 은 code 존중"""
        extra_headers = getattr(exc, "headers", None)
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            return error_response(
                request,
                exc.status_code,
                exc.detail["code"],
                exc.detail.get("message", ""),
                exc.detail.get("details"),
                extra_headers,
            )
        code = _DEFAULT_ERROR_CODES.get(exc.status_code, _FALLBACK_ERROR_CODE)
        return error_response(request, exc.status_code, code, str(exc.detail), None, extra_headers)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """요청 검증 실패 → 400, 필드별 details"""
        details = [
            {
                "field": ".".join(str(part) for part in err["loc"] if part != "body"),
                "value": jsonable_encoder(err.get("input")),
                "reason": err["msg"],
            }
            for err in exc.errors()
        ]
        return error_response(request, 400, "INVALID_REQUEST", "요청값이 올바르지 않습니다.", details)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """미처리 예외 → 500, 스택 로그"""
        logger.exception("unhandled error: %s %s", request.method, request.url.path, exc_info=exc)
        return error_response(request, 500, _FALLBACK_ERROR_CODE, "서버 내부 오류가 발생했습니다.")
