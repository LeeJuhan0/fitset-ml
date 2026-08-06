# ─────────────────────────────────────────────────────────────────────────────
# Composition Root — 앱 조립 지점. 각 도메인 라우터를 모아 하나의 FastAPI 앱으로 묶는다.
# 실행: uvicorn app.main:app  (변수 `app`이 ASGI 진입점)
# 응답 규약은 ai-server·스프링 백엔드와 동일 — 성공 {traceId, data}, 실패 {traceId, error}.
# ─────────────────────────────────────────────────────────────────────────────
import logging
import uuid

from fastapi import FastAPI, Request, Response            # FastAPI: ASGI 웹앱 본체 클래스
from fastapi.encoders import jsonable_encoder             # 검증 에러 객체 → JSON 직렬화 가능 형태
from fastapi.exceptions import RequestValidationError     # 요청 바디/쿼리 검증 실패
from fastapi.middleware.cors import CORSMiddleware        # 브라우저 교차출처(CORS) 허용 미들웨어
from fastapi.responses import JSONResponse                # 핸들러에서 직접 JSON 응답 생성
from fastapi.staticfiles import StaticFiles               # 정적 파일(대시보드) 서빙용
from starlette.exceptions import HTTPException as StarletteHTTPException   # FastAPI HTTPException의 부모(라우트 404 포함)

# 각 도메인의 APIRouter를 별칭으로 가져온다. (router 객체 = 해당 도메인의 엔드포인트 묶음)
from app.core.schemas import ErrorResponse                  # 실패 응답 스키마 — OpenAPI 문서화용
from app.data.router import router as data_router          # GET /data, /data/presigned-url, POST /data/upload-confirm
from app.training.router import router as train_router     # POST /train, GET /train/status, /runs, /runs/{id}/history
from app.deployment.router import router as deploy_router  # POST /deploy, GET /model/latest, /model/version-stats

logger = logging.getLogger("fitset-ml")

# FastAPI(title, version) : OpenAPI 문서(/docs)에 표시되는 메타. app은 모든 라우트·미들웨어의 컨테이너.
app = FastAPI(title="FitSet ML Server", version="1.0.0")

# add_middleware(미들웨어클래스, **옵션) : 모든 요청/응답을 감싸는 처리기 등록.
# CORSMiddleware 옵션은 "무엇을 허용할지" — 전부 "*"(전체 허용, 개발 편의/관리자용).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 허용 출처(도메인). "*" = 모든 사이트에서 호출 허용
    allow_methods=["*"],   # 허용 HTTP 메서드(GET/POST/...). "*" = 전부
    allow_headers=["*"],   # 허용 요청 헤더. "*" = 전부
)

TRACE_ID_HEADER = "X-Trace-Id"


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next) -> Response:
    # 요청마다 traceId를 정해 request.state에 심고 응답 헤더로 되돌린다.
    # 게이트웨이나 다른 서버가 X-Trace-Id를 보내면 그 값을 이어받아 서버 간 추적이 이어진다.
    request.state.trace_id = request.headers.get(TRACE_ID_HEADER) or uuid.uuid4().hex
    response = await call_next(request)
    response.headers[TRACE_ID_HEADER] = request.state.trace_id
    return response


# ── 전역 예외 핸들러 — 실패 응답 {traceId, error: {code, message, details}} 조립 ──
# 상태코드는 그대로 유지하고 본문 형태만 규약에 맞춘다. 시맨틱 코드는 상태코드에서 유도.

_DEFAULT_ERROR_CODES = {
    400: "INVALID_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",   # 중복 학습 시작 등 비즈니스 충돌 — 서버 오류(INTERNAL_ERROR)와 구분
}
_FALLBACK_ERROR_CODE = "INTERNAL_ERROR"


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list | None = None,
) -> JSONResponse:
    # 실패 응답 JSON 조립 — traceId는 미들웨어가 state에 넣은 값을 그대로 쓴다.
    # X-Trace-Id 헤더도 여기서 직접 싣는다 — 처리되지 않은 500은 Starlette의
    # ServerErrorMiddleware가 사용자 미들웨어 바깥에서 응답을 만들어, 미들웨어의
    # 헤더 부착이 건너뛰어지기 때문(트레이싱이 가장 필요한 케이스라 핸들러에서 보장).
    trace_id = getattr(request.state, "trace_id", "")
    return JSONResponse(
        status_code=status_code,
        headers={TRACE_ID_HEADER: trace_id},
        content={
            "traceId": trace_id,
            "error": {"code": code, "message": message, "details": details or []},
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # 서비스/라우터가 던진 HTTPException(400/404/409...)과 라우트 없음(404)을 실패 응답으로 변환.
    # detail이 {code, message} dict면 시맨틱 코드를 그대로 쓴다(ai-server와 동일 규칙).
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        return _error_response(
            request,
            exc.status_code,
            exc.detail["code"],
            exc.detail.get("message", ""),
            exc.detail.get("details"),
        )
    code = _DEFAULT_ERROR_CODES.get(exc.status_code, _FALLBACK_ERROR_CODE)
    return _error_response(request, exc.status_code, code, str(exc.detail))


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
    return _error_response(request, 400, "INVALID_REQUEST", "요청값이 올바르지 않습니다.", details)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # 예상 못 한 예외(S3 재시도 초과, MLflow 연결 실패 등) — 내부 정보는 숨기고 500으로 변환.
    # 응답만 만들고 끝내면 스택트레이스가 어디에도 안 남아 원인 추적이 불가능해진다 —
    # traceId와 함께 stdout(docker logs)에 반드시 남긴다.
    logger.exception(
        "unhandled error: %s %s [%s]",
        request.method, request.url.path, getattr(request.state, "trace_id", "-"),
        exc_info=exc,
    )
    return _error_response(request, 500, _FALLBACK_ERROR_CODE, "서버 내부 오류가 발생했습니다.")


# include_router(router) : 그 라우터의 모든 엔드포인트를 앱에 등록. (순서는 동작에 영향 없음)
# responses=... : 모든 엔드포인트의 OpenAPI 문서(/docs)에 실패 응답 형태를 명시 —
#   실제 조립은 위 예외 핸들러가 하고, ErrorResponse 스키마는 문서화로만 쓰인다.
_ERROR_DOC = {"default": {"model": ErrorResponse, "description": "실패 — {traceId, error: {code, message, details}}"}}
app.include_router(data_router, responses=_ERROR_DOC)
app.include_router(train_router, responses=_ERROR_DOC)
app.include_router(deploy_router, responses=_ERROR_DOC)

# mount("/", StaticFiles(...)) : 루트 경로에 정적 파일 서버를 붙임 → static/ 의 대시보드(HTML/JS) 서빙.
#   directory="static": 서빙할 폴더, html=True: 디렉토리 요청 시 index.html 반환.
#   주의: "/"에 마운트하므로 위 API 라우트들보다 "나중에" 둬야 API가 가려지지 않는다.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
