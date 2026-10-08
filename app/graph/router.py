from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.schemas import ApiResponse, FilenameRequest
from app.core.security import check_basic_auth
from app.deps import DbSessionDep, get_trace_id, validate_platform
from app.graph import service
from app.graph.schemas import ImuResponse

router = APIRouter(tags=["graph"], dependencies=[Depends(check_basic_auth)])


@router.get("/{platform}/graph/imu", response_model=ApiResponse[ImuResponse])
async def imu(
    session: DbSessionDep,
    query: Annotated[FilenameRequest, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """학습 CSV 6축 파형, 시작 기준 초"""
    return ApiResponse(trace_id=trace_id, data=await service.file_imu(session, platform, query.filename))
