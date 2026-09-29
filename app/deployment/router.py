from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.security import check_basic_auth
from app.deps import DbSessionDep, get_trace_id, validate_platform
from app.core.schemas import ApiResponse
from app.deployment import service
from app.deployment.schemas import DeployResponse, DeployRequest, InternalModelsRequest, InternalModelsResponse

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
    """지정 버전 dev 또는 prod 배포, 이력 기록"""
    return ApiResponse(trace_id=trace_id, data=await service.deploy(session, platform, payload.version, payload.env))


@admin_router.get("/{platform}/models/deployed", response_model=ApiResponse[InternalModelsResponse])
async def models_deployed_admin(
    session: DbSessionDep,
    query: Annotated[InternalModelsRequest, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """대시보드용 환경별 현재 배포, 인터널과 같은 응답"""
    return ApiResponse(trace_id=trace_id, data=await service.internal_latest(session, platform, query.env))


@internal_router.get("/{platform}/models/latest", response_model=ApiResponse[InternalModelsResponse])
async def models_latest_internal(
    session: DbSessionDep,
    query: Annotated[InternalModelsRequest, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """백엔드용 환경별 분류, 종목별 렙카운팅 최신 모델"""
    return ApiResponse(trace_id=trace_id, data=await service.internal_latest(session, platform, query.env))
