from fastapi import APIRouter, Depends

from app.core.security import check_basic_auth
from app.deps import DbSessionDep, get_trace_id, validate_platform
from app.core.schemas import ApiResponse
from app.deployment import service
from app.deployment.schemas import DeployResponse, DeployRequest, InternalModelsResponse, ModelLatestResponse, VersionStatsResponse

admin_router = APIRouter(
    tags=["deployment"],
    dependencies=[Depends(check_basic_auth)],
)

internal_router = APIRouter(
    prefix="/internal",
    tags=["internal"],
)


@admin_router.post("/{platform}/deploy", response_model=ApiResponse[DeployResponse])
async def deploy(
    payload: DeployRequest,
    session: DbSessionDep,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """지정 버전 배포, latest 갱신, 이력 기록"""
    return ApiResponse(trace_id=trace_id, data=await service.deploy(session, platform, payload.version))


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


@internal_router.get("/{platform}/models/latest", response_model=ApiResponse[InternalModelsResponse])
async def models_latest_internal(
    session: DbSessionDep,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """백엔드용 분류, 종목별 렙카운팅 최신 모델"""
    return ApiResponse(trace_id=trace_id, data=await service.internal_latest(session, platform))
