# ─────────────────────────────────────────────────────────────────────────────
# training 도메인 API(controller) — 학습 시작/진행률/이력. 유스케이스는 service에 위임.
# 엔드포인트: POST /train(202), GET /train/status, GET /runs, GET /runs/{run_id}/history
# ─────────────────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, Query

from app.deps import validate_platform
from app.core.schemas import Envelope
from app.training import service
from app.training.schemas import (
    MetricHistoryData,
    RunsData,
    TrainRequest,
    TrainStartData,
    TrainStatusData,
)

router = APIRouter()


@router.post("/api/v1/{platform}/train", status_code=202, response_model=Envelope[TrainStartData])
def start_training(body: TrainRequest, platform: str = Depends(validate_platform)):
    # status_code=202 → 성공 시 "접수됨". 완료를 기다리지 않고 즉시 반환.
    data = service.start_training(platform, body.files, body.epochs, body.lr)
    return {
        "success": True,
        "code": "202",
        "message": "학습을 시작했습니다.",
        "data": data,
    }


@router.get("/api/v1/{platform}/train/status", response_model=Envelope[TrainStatusData])
def train_status(
    job_id: str = Query(..., alias="jobId"),   # 쿼리 ?jobId= (start_training이 준 run_id)
    platform: str = Depends(validate_platform),
):
    return {
        "success": True,
        "code": "200",
        "message": "학습 진행률을 조회했습니다.",
        "data": service.get_status(platform, job_id),
    }


@router.get("/api/v1/{platform}/runs", response_model=Envelope[RunsData])
def list_runs(platform: str = Depends(validate_platform)):
    return {
        "success": True,
        "code": "200",
        "data": service.list_runs(platform),
    }


@router.get("/api/v1/{platform}/runs/{run_id}/history", response_model=Envelope[MetricHistoryData])
def run_metric_history(run_id: str, metric: str = "val_loss", platform: str = Depends(validate_platform)):
    # run_id: 경로 변수,  metric: 쿼리 ?metric=(기본 val_loss)
    return {
        "success": True,
        "code": "200",
        "data": service.metric_history(run_id, metric),
    }
