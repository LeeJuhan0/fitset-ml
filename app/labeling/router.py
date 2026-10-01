from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.schemas import ApiResponse, FilenameRequest
from app.data.schemas import PresignedUrlRequest
from app.core.security import check_basic_auth
from app.deps import DbSessionDep, get_trace_id, validate_platform
from app.labeling import service
from app.labeling.models import CollectFileRead
from app.labeling.schemas import (
    ChangeClassRequest,
    DeleteFileResponse,
    EditPhasesRequest,
    ImuResponse,
    LabelResponse,
    LabelRequest,
    ListFilesResponse,
    PoseResponse,
    PresignedPairResponse,
    PromoteResponse,
    PromoteRequest,
    UploadConfirmResponse,
    UploadConfirmRequest,
    VideoUrlResponse,
)

router = APIRouter(tags=["labeling"], dependencies=[Depends(check_basic_auth)])


@router.get("/{platform}/phase/presigned-url", response_model=ApiResponse[PresignedPairResponse])
async def presigned_url(
    session: DbSessionDep,
    query: Annotated[PresignedUrlRequest, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """presigned PUT 쌍 발급"""
    return ApiResponse(trace_id=trace_id, data=await service.issue_upload_urls(session, platform, query.class_name, query.device_id))


@router.post("/{platform}/phase/upload-confirm", response_model=ApiResponse[UploadConfirmResponse])
async def upload_confirm(
    session: DbSessionDep,
    payload: UploadConfirmRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """업로드 확정"""
    return ApiResponse(trace_id=trace_id, data=await service.confirm_upload(session, platform, payload.filename, payload.video_start, payload.rows))


@router.get("/{platform}/phase/files", response_model=ApiResponse[ListFilesResponse])
async def list_files(
    session: DbSessionDep,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """목록 목록, 상태별 개수"""
    return ApiResponse(trace_id=trace_id, data=await service.files(session, platform))


@router.delete("/{platform}/phase/files", response_model=ApiResponse[DeleteFileResponse])
async def delete_file(
    session: DbSessionDep,
    query: Annotated[FilenameRequest, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """수집 파일 삭제, S3 객체와 목록 행"""
    return ApiResponse(trace_id=trace_id, data=await service.delete_file(session, platform, query.filename))


@router.patch("/{platform}/phase/files/class", response_model=ApiResponse[CollectFileRead])
async def change_class(
    session: DbSessionDep,
    payload: ChangeClassRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """종목 변경, 파일명 재채번, 라벨 초기화, 승격 후 409"""
    return ApiResponse(trace_id=trace_id, data=await service.change_class(session, platform, payload.filename, payload.class_name))


@router.patch("/{platform}/phase/files/phases", response_model=ApiResponse[CollectFileRead])
async def edit_phases(
    session: DbSessionDep,
    payload: EditPhasesRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """구간 수동 수정, 프레임별 phase, 승격 후 409"""
    return ApiResponse(trace_id=trace_id, data=await service.edit_phases(session, platform, payload.filename, payload.phases))


@router.post("/{platform}/phase/label", response_model=ApiResponse[LabelResponse], status_code=202)
async def label(
    session: DbSessionDep,
    payload: LabelRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """라벨링 시작, 202"""
    return ApiResponse(trace_id=trace_id, data=await service.start_labeling(session, platform, payload.filenames))


@router.get("/{platform}/phase/video-url", response_model=ApiResponse[VideoUrlResponse])
async def video_url(
    session: DbSessionDep,
    query: Annotated[FilenameRequest, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """영상 presigned GET"""
    return ApiResponse(trace_id=trace_id, data=await service.video_url(session, platform, query.filename))


@router.get("/{platform}/phase/pose", response_model=ApiResponse[PoseResponse])
async def pose(
    session: DbSessionDep,
    query: Annotated[FilenameRequest, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """관절 phase JSON"""
    return ApiResponse(trace_id=trace_id, data=await service.pose(session, platform, query.filename))


@router.get("/{platform}/phase/imu", response_model=ApiResponse[ImuResponse])
async def imu(
    session: DbSessionDep,
    query: Annotated[FilenameRequest, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """라벨 parquet IMU 파형, 영상 시작 기준 시각"""
    return ApiResponse(trace_id=trace_id, data=await service.imu(session, platform, query.filename))


@router.post("/{platform}/phase/promote", response_model=ApiResponse[PromoteResponse])
async def promote(
    session: DbSessionDep,
    payload: PromoteRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """승격, 라벨 parquet 를 dataset 버킷과 dataset_files 로"""
    return ApiResponse(trace_id=trace_id, data=await service.promote(session, platform, payload.filenames))
