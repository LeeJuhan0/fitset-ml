# ─────────────────────────────────────────────────────────────────────────────
# deployment 도메인 API(controller) — 배포/최신 모델 조회/버전 분포. 유스케이스는 service에 위임.
# 라우터 2개로 분리 — 호출 주체가 다르면 인증도 다르다:
#   router(유저, /api/v1):        GET /model/latest — 앱 폴링
#   admin_router(어드민, /api/admin/v1): POST /deploy, GET /model/version-stats — 배포·대시보드
# ─────────────────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, Query

from app.core.security import check_basic_auth
from app.deps import get_current_user_id, get_trace_id, validate_platform
from app.core.schemas import ApiResponse
from app.deployment import service
from app.deployment.schemas import DeployData, DeployRequest, ModelLatestData, VersionStatsData

router = APIRouter(                             # 유저용 — 앱 폴링, 전 엔드포인트에 JWT 검증
    prefix="/api/v1",
    dependencies=[Depends(get_current_user_id)],
)
admin_router = APIRouter(                       # 어드민용 — 전 엔드포인트에 Basic 인증
    prefix="/api/admin/v1",
    dependencies=[Depends(check_basic_auth)],
)


@admin_router.post("/{platform}/deploy", response_model=ApiResponse[DeployData])
def deploy(
    body: DeployRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    return {"trace_id": trace_id, "data": service.deploy(platform, body.version)}


@router.get("/{platform}/model/latest", response_model=ApiResponse[ModelLatestData])
def model_latest(
    current_version: str | None = Query(None, alias="currentVersion"),   # 쿼리 ?currentVersion= (앱의 현재 버전, 선택)
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    return {"trace_id": trace_id, "data": service.latest(platform, current_version)}


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
    # 대시보드용 알리아스 — 유저 경로(JWT)와 달리 Basic으로 열고, currentVersion을 받지
    # 않아 버전 분포 집계를 오염시키지 않는다(집계는 앱 폴링 전용).
    return {"trace_id": trace_id, "data": service.latest(platform, None)}
