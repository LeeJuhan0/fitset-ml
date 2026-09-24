from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.security import check_basic_auth
from app.deps import DbSessionDep, get_trace_id, validate_platform
from app.core.schemas import ApiResponse
from app.training import service
from app.training.schemas import (
    JobIdRequest,
    MetricRequest,
    MetricHistoryResponse,
    RunsResponse,
    TrainRequest,
    TrainStartResponse,
    TrainStatusResponse,
)

router = APIRouter(tags=["training"], dependencies=[Depends(check_basic_auth)])


@router.post("/{platform}/train", status_code=202, response_model=ApiResponse[TrainStartResponse])
async def start_training(
    session: DbSessionDep,
    payload: TrainRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """학습 시작, 202"""
    return ApiResponse(trace_id=trace_id, data=await service.start_training(session, platform, payload.files, epochs=payload.epochs, lr=payload.lr))


@router.get("/{platform}/train/status", response_model=ApiResponse[TrainStatusResponse])
def train_status(
    query: Annotated[JobIdRequest, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """MLflow run 상태 조회"""
    return ApiResponse(trace_id=trace_id, data=service.get_status(platform, query.job_id))


@router.get("/{platform}/runs", response_model=ApiResponse[RunsResponse])
def list_runs(
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """최근 run 목록과 best run"""
    return ApiResponse(trace_id=trace_id, data=service.list_runs(platform))


@router.get("/{platform}/runs/{run_id}/history", response_model=ApiResponse[MetricHistoryResponse])
def run_metric_history(
    run_id: str,
    query: Annotated[MetricRequest, Query()],
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    """run 메트릭 시계열"""
    return ApiResponse(trace_id=trace_id, data=service.metric_history(run_id, query.metric))
