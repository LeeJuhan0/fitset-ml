from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.schemas import ApiResponse
from app.core.security import check_basic_auth
from app.deps import DbSessionDep, get_trace_id, validate_platform
from app.phase import service
from app.phase.models import PhaseModelRead
from app.phase.schemas import (
    ListModelsResponse,
    ModelFormatRequest,
    ModelUrlResponse,
    ModelsRequest,
    PhaseTrainResponse,
    PhaseTrainRequest,
)

router = APIRouter(tags=["phase"], dependencies=[Depends(check_basic_auth)])


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


@router.get("/{platform}/phase/models/deployed", response_model=ApiResponse[ListModelsResponse])
async def deployed_models(
    session: DbSessionDep,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """종목별 배포된 렙카운팅 모델, 앱이 버전 확인에 사용"""
    return ApiResponse(trace_id=trace_id, data=await service.deployed_models(session, platform))


@router.post("/{platform}/phase/models/{model_id}/deploy", response_model=ApiResponse[PhaseModelRead])
async def deploy_model(
    session: DbSessionDep,
    model_id: int,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """렙카운팅 모델 배포, 같은 종목 기존 배포 교체, 롤백 겸용"""
    return ApiResponse(trace_id=trace_id, data=await service.deploy_model(session, platform, model_id))


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
