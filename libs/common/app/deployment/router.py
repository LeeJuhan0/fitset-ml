# ─────────────────────────────────────────────────────────────────────────────
# deployment 도메인 API(controller) — 배포/최신 모델 조회/버전 분포. 유스케이스는 service에 위임.
# 어드민 전용 — admin_router(/api/v1): POST /deploy, GET /model/version-stats·latest. 유저 표면은 2026-09-19 제거.
# ─────────────────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends

from app.core.security import check_basic_auth
from app.deps import get_trace_id, validate_platform
from app.core.schemas import ApiResponse
from app.deployment import service
from app.deployment.schemas import DeployData, DeployRequest, ModelLatestData, VersionStatsData

# prefix(/api/v1)는 admin_api main이 등록한다
admin_router = APIRouter(                       # 어드민용 — 전 엔드포인트에 Basic 인증
    dependencies=[Depends(check_basic_auth)],
)


@admin_router.post("/{platform}/deploy", response_model=ApiResponse[DeployData])
def deploy(
    body: DeployRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    return {"trace_id": trace_id, "data": service.deploy(platform, body.version)}


@admin_router.get("/{platform}/model/version-stats", response_model=ApiResponse[VersionStatsData])
def version_stats(
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    return {"trace_id": trace_id, "data": service.version_stats(platform)}


@admin_router.get("/{platform}/model/latest", response_model=ApiResponse[ModelLatestData])
def model_latest_admin(
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    # 대시보드용 조회 — currentVersion을 받지 않아 버전 분포 집계에 기록되지 않는다
    return {"trace_id": trace_id, "data": service.latest(platform, None)}
