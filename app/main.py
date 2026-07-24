# ─────────────────────────────────────────────────────────────────────────────
# Composition Root — 앱 조립 지점. 각 도메인 라우터를 모아 하나의 FastAPI 앱으로 묶는다.
# 실행: uvicorn app.main:app  (변수 `app`이 ASGI 진입점)
# ─────────────────────────────────────────────────────────────────────────────
from fastapi import FastAPI, Request                     # FastAPI: ASGI 웹앱 본체 클래스
from fastapi.encoders import jsonable_encoder             # 검증 에러 객체 → JSON 직렬화 가능 형태
from fastapi.exceptions import RequestValidationError     # 요청 바디/쿼리 검증 실패(422)
from fastapi.middleware.cors import CORSMiddleware        # 브라우저 교차출처(CORS) 허용 미들웨어
from fastapi.responses import JSONResponse                # 핸들러에서 직접 JSON 응답 생성
from fastapi.staticfiles import StaticFiles               # 정적 파일(대시보드) 서빙용
from starlette.exceptions import HTTPException as StarletteHTTPException   # FastAPI HTTPException의 부모(라우트 404 포함)

# 각 도메인의 APIRouter를 별칭으로 가져온다. (router 객체 = 해당 도메인의 엔드포인트 묶음)
from app.data.router import router as data_router          # GET /data, /data/presigned-url, POST /data/upload-confirm
from app.training.router import router as train_router     # POST /train, GET /train/status, /runs, /runs/{id}/history
from app.deployment.router import router as deploy_router  # POST /deploy, GET /model/latest, /model/version-stats

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

# ── 전역 예외 핸들러 — 에러 응답도 성공과 같은 봉투 {success, code, message, data} 로 통일 ──
# 상태코드는 그대로 유지하고 본문 형태만 바꾼다. 수집 앱은 상태코드만 보므로 영향 없음.

def _error_envelope(status_code: int, message: str, data=None) -> JSONResponse:
    # 봉투 규칙: 실패는 success=False, code=상태코드 문자열, data는 부가정보(없으면 None)
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "code": str(status_code), "message": message, "data": data},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # 서비스/라우터가 던진 HTTPException(400/404/409...)과 라우트 없음(404)을 봉투로 변환
    return _error_envelope(exc.status_code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # 요청 스키마 검증 실패(422) — 어떤 필드가 왜 틀렸는지는 data에 담아준다
    return _error_envelope(422, "요청 형식이 올바르지 않습니다.", jsonable_encoder(exc.errors()))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # 예상 못 한 예외(S3 재시도 초과, MLflow 연결 실패 등) — 내부 정보는 숨기고 봉투만 반환
    return _error_envelope(500, "서버 내부 오류가 발생했습니다.")


# include_router(router) : 그 라우터의 모든 엔드포인트를 앱에 등록. (순서는 동작에 영향 없음)
app.include_router(data_router)
app.include_router(train_router)
app.include_router(deploy_router)

# mount("/", StaticFiles(...)) : 루트 경로에 정적 파일 서버를 붙임 → static/ 의 대시보드(HTML/JS) 서빙.
#   directory="static": 서빙할 폴더, html=True: 디렉토리 요청 시 index.html 반환.
#   주의: "/"에 마운트하므로 위 API 라우트들보다 "나중에" 둬야 API가 가려지지 않는다.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
