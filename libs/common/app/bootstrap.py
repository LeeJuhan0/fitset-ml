# ─────────────────────────────────────────────────────────────────────────────
# 공통 앱 조립(bootstrap) — user_api·admin_api 두 서비스가 공유하는 뼈대.
# 응답 규약(성공 {traceId, data} / 실패 {traceId, error})과 관측(traceId 로깅·액세스
# 로그)은 서비스가 갈라져도 동일해야 하므로 여기가 정본이다.
# 각 서비스 엔트리포인트는 create_base_app()으로 뼈대를 받고 라우터만 include한다.
# ─────────────────────────────────────────────────────────────────────────────
import logging
import time      # 액세스 로그의 소요 시간 측정
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder             # 검증 에러 객체 → JSON 직렬화 가능 형태
from fastapi.exceptions import RequestValidationError     # 요청 바디/쿼리 검증 실패
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException   # 라우트 404 포함 부모 예외

from app.core import security                              # 어드민 Basic — 정적 대시보드 보호에 사용
from app.core.logging import configure_logging, trace_id_var   # traceId 자동 첨부 로깅
from app.core.schemas import ErrorResponse                  # 실패 응답 스키마 — OpenAPI 문서화용

logger = logging.getLogger("fitset-ml")

TRACE_ID_HEADER = "X-Trace-Id"

# include_router(..., responses=ERROR_DOC) : OpenAPI 문서에 실패 응답 형태를 명시 —
# 실제 조립은 예외 핸들러가 하고, ErrorResponse 스키마는 문서화로만 쓰인다.
ERROR_DOC = {"default": {"model": ErrorResponse, "description": "실패 — {traceId, error: {code, message, details}}"}}

# ── 실패 응답 조립 — 시맨틱 코드는 상태코드에서 유도, detail dict면 그대로 존중 ──

_DEFAULT_ERROR_CODES = {
    400: "INVALID_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",   # 중복 학습 시작 등 비즈니스 충돌 — 서버 오류(INTERNAL_ERROR)와 구분
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
    # 실패 응답 JSON 조립 — traceId는 미들웨어가 state에 넣은 값을 그대로 쓴다.
    # X-Trace-Id 헤더도 여기서 직접 싣는다 — 처리되지 않은 500은 Starlette의
    # ServerErrorMiddleware가 사용자 미들웨어 바깥에서 응답을 만들어, 미들웨어의
    # 헤더 부착이 건너뛰어지기 때문(트레이싱이 가장 필요한 케이스라 핸들러에서 보장).
    # extra_headers: 예외가 실어 보낸 헤더(WWW-Authenticate 등) 보존용.
    trace_id = getattr(request.state, "trace_id", "")
    return JSONResponse(
        status_code=status_code,
        headers={TRACE_ID_HEADER: trace_id, **(extra_headers or {})},
        content={
            "traceId": trace_id,
            "error": {"code": code, "message": message, "details": details or []},
        },
    )


def _register_exception_handlers(app: FastAPI) -> None:
    # 전역 예외 핸들러 3종 — 상태코드는 유지하고 본문 형태만 규약에 맞춘다

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        # 서비스/라우터가 던진 HTTPException(400/404/409...)과 라우트 없음(404)을 실패 응답으로 변환.
        # detail이 {code, message} dict면 시맨틱 코드를 그대로 쓴다(ai-server와 동일 규칙).
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
        # 요청 스키마 검증 실패 — 규약에 맞춰 400 INVALID_REQUEST, 필드별 사유는 details에
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
        # 예상 못 한 예외(S3 재시도 초과, MLflow 연결 실패 등) — 내부 정보는 숨기고 500으로 변환.
        # traceId는 로깅 필터(core/logging.py)가 모든 레코드에 붙인다 — 메시지에 중복 기재하지 않는다
        logger.exception("unhandled error: %s %s", request.method, request.url.path, exc_info=exc)
        return error_response(request, 500, _FALLBACK_ERROR_CODE, "서버 내부 오류가 발생했습니다.")


# Basic 없이 통과시키는 경로 — API·프록시는 각자 계층 인증(JWT·Basic)을 가지고, 문서·헬스체크는 공개
_STATIC_AUTH_EXEMPT_PREFIXES = ("/api/", "/mlflow", "/docs", "/openapi.json", "/redoc")


def _register_static_basic_guard(app: FastAPI) -> None:
    # 대시보드 정적 파일("/" 마운트)도 어드민 자산이라 Basic을 요구한다 — admin_api 전용.
    # 페이지 진입 시 브라우저 팝업으로 인증되면, 이후 같은 realm의 /api/v1/* fetch에도
    # 브라우저가 캐시된 크리덴셜을 자동으로 실어 보낸다 — 대시보드에 로그인 화면이 필요 없다.

    @app.middleware("http")
    async def static_basic_auth_middleware(request: Request, call_next) -> Response:
        if request.url.path.startswith(_STATIC_AUTH_EXEMPT_PREFIXES):
            return await call_next(request)
        if not security.credentials_configured():
            return error_response(request, 503, "ADMIN_AUTH_LOCKED", "관리자 자격증명이 설정되지 않았습니다.")
        if not security.basic_header_valid(request.headers.get("Authorization", "")):
            return error_response(
                request, 401, "UNAUTHORIZED", "관리자 인증에 실패했습니다.",
                extra_headers={"WWW-Authenticate": 'Basic realm="FitSet Admin"'},
            )
        return await call_next(request)


def _register_trace_middleware(app: FastAPI) -> None:
    # 요청의 traceId를 state·로그 컨텍스트·응답 헤더에 전파하고, 완료를 한 줄로 남긴다.
    # 게이트웨이나 다른 서버가 X-Trace-Id를 보내면 그 값을 이어받아 서버 간 추적이 이어진다.
    # 같은 값을 request.state와 ContextVar 두 곳에 넣는 이유 — request를 가진 코드(deps·핸들러)는
    # state에서, 못 가진 코드(콜스택 깊은 곳의 로깅 필터)는 ContextVar에서 읽는다.
    # uvicorn 액세스 로그를 끈 대신(core/logging.py) 여기서 유일한 액세스 로그를 낸다.

    @app.middleware("http")
    async def trace_id_middleware(request: Request, call_next) -> Response:
        request.state.trace_id = request.headers.get(TRACE_ID_HEADER) or uuid.uuid4().hex
        token = trace_id_var.set(request.state.trace_id)
        started = time.perf_counter()

        # 예외 핸들러가 못 잡은 예외로 call_next가 죽으면 status가 500인 채 finally로 간다
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers[TRACE_ID_HEADER] = request.state.trace_id
            return response
        finally:
            _log_access(request, status, started)
            trace_id_var.reset(token)   # 문맥 반납 — 다음 요청에 안 샌다


def _log_access(request: Request, status: int, started: float) -> None:
    """요청 완료 1줄. 상태에 따라 레벨을 나눠 CloudWatch 필터가 의미를 갖게 한다.

    헬스체크는 남기지 않는다 — ELB가 주기 호출로 실 트래픽 로그를 덮는다(ai-server 실측).
    """
    if request.url.path == "/api/health":
        return
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.log(
        _level_for(status), "%s %s %d %.0fms", request.method, request.url.path, status, elapsed_ms,
    )


def _level_for(status: int) -> int:
    # 상태 코드 → 로그 레벨. 5xx는 서버 장애, 4xx는 클라 잘못, 나머지는 정상
    if status >= 500:
        return logging.ERROR
    if status >= 400:
        return logging.WARNING
    return logging.INFO


def create_base_app(title: str, *, protect_static: bool = False) -> FastAPI:
    """서비스 공통 뼈대를 조립한 FastAPI 앱을 돌려준다.

    포함: 로깅 설정, CORS, 전역 예외 핸들러, (선택) 정적 Basic 가드, trace 미들웨어, /api/health.
    미들웨어 순서는 여기서만 보장한다 — Starlette는 나중에 등록된 미들웨어가 바깥을
    감싸므로 trace를 마지막에 등록해 최외곽으로 만든다(정적 Basic 401도 traceId·액세스
    로그를 갖는다). 호출자가 이후에 미들웨어를 추가하면 이 보장이 깨지므로 금지.
    protect_static: admin_api처럼 "/"에 정적 대시보드를 마운트하는 서비스만 True.
    """
    configure_logging()   # 포맷에 [traceId] 첨부 + uvicorn 액세스 로그 대체 (core/logging.py)

    app = FastAPI(title=title, version="1.0.0")

    # CORS — 전부 "*"(전체 허용, 개발 편의/관리자용)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_exception_handlers(app)
    if protect_static:
        _register_static_basic_guard(app)
    _register_trace_middleware(app)   # 반드시 마지막 등록 — 최외곽

    @app.get("/api/health")
    def health(request: Request):
        # 배포 헬스체크용 — 앱이 요청을 받는지만 확인한다(외부 의존성 검사 없음).
        return {"traceId": request.state.trace_id, "data": {"status": "ok"}}

    return app
