from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.schemas import ApiResponse, FilenameQuery
from app.data.schemas import PresignedUrlQuery
from app.core.security import check_basic_auth
from app.deps import DbSessionDep, get_trace_id, validate_platform
from app.phase import service
from app.phase.schemas import (
    LabelData,
    LabelRequest,
    ListFilesData,
    ListModelsData,
    ModelFormatQuery,
    ModelUrlData,
    ModelsQuery,
    PhaseTrainData,
    PhaseTrainRequest,
    PoseData,
    PresignedPairData,
    PromoteData,
    PromoteRequest,
    UploadConfirmData,
    UploadConfirmRequest,
    VideoUrlData,
)

router = APIRouter(tags=["phase"], dependencies=[Depends(check_basic_auth)])


@router.get("/{platform}/phase/presigned-url", response_model=ApiResponse[PresignedPairData])
async def presigned_url(
    session: DbSessionDep,
    query: Annotated[PresignedUrlQuery, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """presigned PUT 쌍 발급"""
    return ApiResponse(trace_id=trace_id, data=await service.issue_upload_urls(session, platform, query))


@router.post("/{platform}/phase/upload-confirm", response_model=ApiResponse[UploadConfirmData])
async def upload_confirm(
    session: DbSessionDep,
    payload: UploadConfirmRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """업로드 확정"""
    return ApiResponse(trace_id=trace_id, data=await service.confirm_upload(session, platform, payload))


@router.get("/{platform}/phase/files", response_model=ApiResponse[ListFilesData])
async def list_files(
    session: DbSessionDep,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """목록 목록, 상태별 개수"""
    return ApiResponse(trace_id=trace_id, data=await service.files(session, platform))


@router.post("/{platform}/phase/label", response_model=ApiResponse[LabelData], status_code=202)
async def label(
    session: DbSessionDep,
    payload: LabelRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """라벨링 시작, 202"""
    return ApiResponse(trace_id=trace_id, data=await service.start_labeling(session, platform, payload))


@router.get("/{platform}/phase/video-url", response_model=ApiResponse[VideoUrlData])
async def video_url(
    session: DbSessionDep,
    query: Annotated[FilenameQuery, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """영상 presigned GET"""
    return ApiResponse(trace_id=trace_id, data=await service.video_url(session, platform, query))


@router.get("/{platform}/phase/pose", response_model=ApiResponse[PoseData])
async def pose(
    session: DbSessionDep,
    query: Annotated[FilenameQuery, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """관절 phase JSON"""
    return ApiResponse(trace_id=trace_id, data=await service.pose(session, platform, query))


@router.post("/{platform}/phase/promote", response_model=ApiResponse[PromoteData])
async def promote(
    session: DbSessionDep,
    payload: PromoteRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """승격, 라벨 parquet 를 dataset 버킷과 dataset_files 로"""
    return ApiResponse(trace_id=trace_id, data=await service.promote(session, platform, payload))


@router.post("/{platform}/phase/train", response_model=ApiResponse[PhaseTrainData], status_code=202)
async def train(
    session: DbSessionDep,
    payload: PhaseTrainRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """종목별 렙카운팅 모델 학습 시작, 202"""
    return ApiResponse(trace_id=trace_id, data=await service.start_phase_training(session, platform, payload))


@router.get("/{platform}/phase/models", response_model=ApiResponse[ListModelsData])
async def models(
    session: DbSessionDep,
    query: Annotated[ModelsQuery, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """렙카운팅 모델 목록, 종목 필터"""
    return ApiResponse(trace_id=trace_id, data=await service.models(session, platform, query))


@router.get("/{platform}/phase/models/{model_id}/download-url", response_model=ApiResponse[ModelUrlData])
async def model_download_url(
    session: DbSessionDep,
    model_id: int,
    query: Annotated[ModelFormatQuery, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """산출물 presigned GET, pt onnx mlpackage"""
    return ApiResponse(trace_id=trace_id, data=await service.model_download_url(session, platform, model_id, query))
