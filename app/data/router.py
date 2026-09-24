from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.schemas import ApiResponse, FilenameRequest
from app.core.security import check_basic_auth
from app.data import service
from app.data.schemas import (
    FileStatsResponse,
    ListDataResponse,
    PresignedUrlResponse,
    PresignedUrlRequest,
    UploadConfirmResponse,
    UploadConfirmRequest,
)
from app.deps import DbSessionDep, get_trace_id, validate_platform

admin_router = APIRouter(tags=["data"], dependencies=[Depends(check_basic_auth)])


@admin_router.get("/{platform}/data", response_model=ApiResponse[ListDataResponse])
async def list_data(
    session: DbSessionDep,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """학습 데이터셋 목록"""
    return ApiResponse(trace_id=trace_id, data=await service.list_data(session, platform))


@admin_router.get("/{platform}/data/stats", response_model=ApiResponse[FileStatsResponse])
async def data_stats(
    session: DbSessionDep,
    query: Annotated[FilenameRequest, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """파일 센서 통계, 앞뒤 트림"""
    return ApiResponse(trace_id=trace_id, data=await service.file_stats(session, platform, query.filename))


@admin_router.get("/{platform}/data/presigned-url", response_model=ApiResponse[PresignedUrlResponse])
async def admin_presigned_url(
    session: DbSessionDep,
    query: Annotated[PresignedUrlRequest, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """어드민 직행 업로드 1단계, 채번, presigned PUT"""
    return ApiResponse(trace_id=trace_id, data=await service.admin_issue_upload_url(session, platform, query.class_name, query.device_id))


@admin_router.post("/{platform}/data/upload-confirm", response_model=ApiResponse[UploadConfirmResponse])
async def admin_upload_confirm(
    session: DbSessionDep,
    payload: UploadConfirmRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """어드민 직행 업로드 2단계, uploaded 확정"""
    return ApiResponse(trace_id=trace_id, data=await service.admin_confirm_upload(session, platform, payload.class_name, payload.filename))
