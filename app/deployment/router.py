from fastapi import APIRouter, Depends

from app.core.security import check_basic_auth
from app.deps import get_trace_id, validate_platform
from app.core.schemas import ApiResponse
from app.deployment import service
from app.deployment.schemas import DeployResponse, DeployRequest, ModelLatestResponse, VersionStatsResponse

admin_router = APIRouter(
    tags=["deployment"],
    dependencies=[Depends(check_basic_auth)],
)


@admin_router.post("/{platform}/deploy", response_model=ApiResponse[DeployResponse])
def deploy(
    payload: DeployRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """지정 버전 배포, latest 갱신"""
    return ApiResponse(trace_id=trace_id, data=service.deploy(platform, payload.version))


@admin_router.get("/{platform}/model/version-stats", response_model=ApiResponse[VersionStatsResponse])
def version_stats(
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """최근 24시간 버전 분포"""
    return ApiResponse(trace_id=trace_id, data=service.version_stats(platform))


@admin_router.get("/{platform}/model/latest", response_model=ApiResponse[ModelLatestResponse])
def model_latest_admin(
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """대시보드용 최신 모델 조회"""
    return ApiResponse(trace_id=trace_id, data=service.latest(platform, None))
