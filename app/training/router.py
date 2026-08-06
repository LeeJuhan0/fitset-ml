# ─────────────────────────────────────────────────────────────────────────────
# training 도메인 API(controller) — 학습 시작/진행률/이력. 유스케이스는 service에 위임.
# 엔드포인트: POST /train(202), GET /train/status, GET /runs, GET /runs/{run_id}/history
# ─────────────────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, Query

from app.deps import get_trace_id, validate_platform
from app.core.schemas import ApiResponse
from app.training import service
from app.training.schemas import (
    MetricHistoryData,
    RunsData,
    TrainRequest,
    TrainStartData,
    TrainStatusData,
)

router = APIRouter()


@router.post("/api/v1/{platform}/train", status_code=202, response_model=ApiResponse[TrainStartData])
def start_training(
    body: TrainRequest,
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    # status_code=202 → 성공 시 "접수됨". 완료를 기다리지 않고 즉시 반환.
    return {"trace_id": trace_id, "data": service.start_training(platform, body.files, body.epochs, body.lr)}


@router.get("/api/v1/{platform}/train/status", response_model=ApiResponse[TrainStatusData])
def train_status(
    job_id: str = Query(..., alias="jobId"),   # 쿼리 ?jobId= (start_training이 준 run_id)
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    return {"trace_id": trace_id, "data": service.get_status(platform, job_id)}


@router.get("/api/v1/{platform}/runs", response_model=ApiResponse[RunsData])
def list_runs(
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    return {"trace_id": trace_id, "data": service.list_runs(platform)}


@router.get("/api/v1/{platform}/runs/{run_id}/history", response_model=ApiResponse[MetricHistoryData])
def run_metric_history(
    run_id: str,
    metric: str = "val_loss",
    platform: str = Depends(validate_platform),
    trace_id: str = Depends(get_trace_id),
):
    # run_id: 경로 변수,  metric: 쿼리 ?metric=(기본 val_loss)
    return {"trace_id": trace_id, "data": service.metric_history(run_id, metric)}
