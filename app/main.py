from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.exception_register import ERROR_DOC, register_exception_handlers
from app.core.logging import configure_logging, register_trace_middleware
from app.core.security import register_static_basic_guard
from app.data.router import admin_router as data_router
from app.deployment.router import admin_router as deploy_router
from app.exercises.router import router as exercises_router
from app.mlflow_proxy import router as mlflow_proxy_router
from app.phase.router import router as phase_router
from app.training.router import router as train_router

OPENAPI_TAGS = [
    {"name": "exercises", "description": "운동 종목 마스터, 모델 출력 인덱스와 slug 매핑, class-mapping 시드"},
    {"name": "data", "description": "학습 데이터셋 목록, 통계, 어드민 직행 업로드, 유저 업로드 승격"},
    {"name": "phase", "description": "수집앱 IMU+영상 업로드, 구간 라벨링, 승격, 종목별 렙카운팅 모델"},
    {"name": "training", "description": "분류 모델 학습 시작, 진행 상태, MLflow 이력"},
    {"name": "deployment", "description": "분류 모델 배포, latest 조회, 버전 분포"},
    {"name": "health", "description": "헬스체크"},
]

STATIC_DIR = Path(__file__).resolve().parent / "static"

configure_logging()

app = FastAPI(title="FitSet ML Admin API", version="1.0.0", openapi_tags=OPENAPI_TAGS)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
register_exception_handlers(app)
register_static_basic_guard(app)
register_trace_middleware(app)


@app.get("/api/health", tags=["health"])
def health(request: Request):
    """배포 헬스체크, 외부 의존성 검사 없음"""
    return {"traceId": request.state.trace_id, "data": {"status": "ok"}}


app.include_router(exercises_router, prefix="/api/v1", responses=ERROR_DOC)
app.include_router(data_router, prefix="/api/v1", responses=ERROR_DOC)
app.include_router(phase_router, prefix="/api/v1", responses=ERROR_DOC)
app.include_router(train_router, prefix="/api/v1", responses=ERROR_DOC)
app.include_router(deploy_router, prefix="/api/v1", responses=ERROR_DOC)
app.include_router(mlflow_proxy_router)

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
