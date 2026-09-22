import logging
import time
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, Request, Response

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


class _TraceIdFilter(logging.Filter):
    """로그 레코드에 traceId 필드 첨부"""
    def filter(self, record: logging.LogRecord) -> bool:
        """ContextVar 의 traceId 를 레코드에 넣는다"""
        if not hasattr(record, "trace_id"):
            record.trace_id = trace_id_var.get()
        return True


def configure_logging() -> None:
    """root 로거의 레벨과 포맷을 설정하고 traceId 필터를 부착한다"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s [%(trace_id)s] %(message)s",
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(_TraceIdFilter())
    logging.getLogger("uvicorn.access").disabled = True


TRACE_ID_HEADER = "X-Trace-Id"
logger = logging.getLogger("fitset-ml")


def register_trace_middleware(app: FastAPI) -> None:
    """traceId 전파, 액세스 로그, 반드시 마지막 등록"""

    @app.middleware("http")
    async def trace_id_middleware(request: Request, call_next) -> Response:
        """traceId 발급·전파, 액세스 로그, ContextVar 반납"""
        request.state.trace_id = request.headers.get(TRACE_ID_HEADER) or uuid.uuid4().hex
        token = trace_id_var.set(request.state.trace_id)
        started = time.perf_counter()

        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers[TRACE_ID_HEADER] = request.state.trace_id
            return response
        finally:
            _log_access(request, status, started)
            trace_id_var.reset(token)


def _log_access(request: Request, status: int, started: float) -> None:
    """요청 완료 로그 1줄, 헬스체크 제외"""
    if request.url.path == "/api/health":
        return
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.log(
        _level_for(status), "%s %s %d %.0fms", request.method, request.url.path, status, elapsed_ms,
    )


def _level_for(status: int) -> int:
    """상태코드 → 로그 레벨"""
    if status >= 500:
        return logging.ERROR
    if status >= 400:
        return logging.WARNING
    return logging.INFO
