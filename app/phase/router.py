from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.schemas import ApiResponse, FilenameRequest
from app.data.schemas import PresignedUrlRequest
from app.core.security import check_basic_auth
from app.deps import DbSessionDep, get_trace_id, validate_platform
from app.phase import service
from app.phase.schemas import (
    LabelResponse,
    LabelRequest,
    ListFilesResponse,
    ListModelsResponse,
    ModelFormatRequest,
    ModelUrlResponse,
    ModelsRequest,
    PhaseTrainResponse,
    PhaseTrainRequest,
    PoseResponse,
    PresignedPairResponse,
    PromoteResponse,
    PromoteRequest,
    UploadConfirmResponse,
    UploadConfirmRequest,
    VideoUrlResponse,
)

router = APIRouter(tags=["phase"], dependencies=[Depends(check_basic_auth)])


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


@router.post("/{platform}/phase/promote", response_model=ApiResponse[PromoteResponse])
async def promote(
    session: DbSessionDep,
    payload: PromoteRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """승격, 라벨 parquet 를 dataset 버킷과 dataset_files 로"""
    return ApiResponse(trace_id=trace_id, data=await service.promote(session, platform, payload.filenames))


@router.post("/{platform}/phase/train", response_model=ApiResponse[PhaseTrainResponse], status_code=202)
async def train(
    session: DbSessionDep,
    payload: PhaseTrainRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """종목별 렙카운팅 모델 학습 시작, 202"""
    return ApiResponse(trace_id=trace_id, data=await service.start_phase_training(session, platform, payload.class_name, payload.filenames, epochs=payload.epochs, lr=payload.lr, window=payload.window, stride=payload.stride))


@router.get("/{platform}/phase/models", response_model=ApiResponse[ListModelsResponse])
async def models(
    session: DbSessionDep,
    query: Annotated[ModelsRequest, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """렙카운팅 모델 목록, 종목 필터"""
    return ApiResponse(trace_id=trace_id, data=await service.models(session, platform, query.class_name))


@router.get("/{platform}/phase/models/{model_id}/download-url", response_model=ApiResponse[ModelUrlResponse])
async def model_download_url(
    session: DbSessionDep,
    model_id: int,
    query: Annotated[ModelFormatRequest, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """산출물 presigned GET, pt onnx mlpackage"""
    return ApiResponse(trace_id=trace_id, data=await service.model_download_url(session, platform, model_id, query.format))
