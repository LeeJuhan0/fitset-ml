import subprocess
import sys
import json

import mlflow
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.web.deps import validate_platform
from app.core.config import settings
from app.core.s3 import get_index, next_version

router = APIRouter()

# platform → {job_id, run_id, process, version, total_epochs}
_running: dict[str, dict] = {}


class TrainRequest(BaseModel):
    files: list[str]
    epochs: int = 200
    lr: float = 0.001


@router.post("/api/v1/{platform}/train", status_code=202)
def start_training(body: TrainRequest, platform: str = Depends(validate_platform)):
    if platform in _running and _running[platform]["process"].poll() is None:
        raise HTTPException(status_code=409, detail="해당 플랫폼 학습이 이미 진행 중입니다.")

    index = get_index(platform)
    valid = {f["filename"] for f in index["files"]}
    invalid = [f for f in body.files if f not in valid]
    if invalid:
        raise HTTPException(status_code=400, detail=f"존재하지 않는 파일: {invalid}")

    version = next_version(platform)

    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    # MlflowClient로 생성 → 상태가 RUNNING으로 유지됨 (end_run 호출 안 함)
    client = mlflow.MlflowClient()
    exp = client.get_experiment_by_name(f"fitset-{platform}")
    if exp is None:
        exp_id = client.create_experiment(f"fitset-{platform}")
    else:
        exp_id = exp.experiment_id
    run = client.create_run(experiment_id=exp_id, run_name=version)
    run_id = run.info.run_id

    import tempfile, pathlib
    log_path = pathlib.Path(tempfile.gettempdir()) / f"trainer_{platform}_{version}.log"
    log_file = open(log_path, "w")

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "app.worker.trainer",
            "--platform", platform,
            "--files", json.dumps(body.files),
            "--epochs", str(body.epochs),
            "--lr", str(body.lr),
            "--run-id", run_id,
            "--version", version,
        ],
        stdout=log_file,
        stderr=log_file,
    )

    _running[platform] = {
        "job_id": run_id,
        "process": proc,
        "version": version,
        "total_epochs": body.epochs,
    }

    return {
        "success": True,
        "code": "202",
        "message": "학습을 시작했습니다.",
        "data": {"jobId": run_id, "experimentId": exp_id, "version": version, "totalEpochs": body.epochs},
    }


@router.get("/api/v1/{platform}/train/status")
def train_status(jobId: str, platform: str = Depends(validate_platform)):
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()

    try:
        run = client.get_run(jobId)
    except Exception:
        raise HTTPException(status_code=404, detail="해당 jobId의 작업이 없습니다.")

    state = run.info.status
    metrics = run.data.metrics
    job = _running.get(platform, {})
    total = job.get("total_epochs", 0)

    status_map = {"RUNNING": "running", "FINISHED": "completed", "FAILED": "failed"}

    return {
        "success": True,
        "code": "200",
        "message": "학습 진행률을 조회했습니다.",
        "data": {
            "status": status_map.get(state, state.lower()),
            "experimentId": run.info.experiment_id,
            "epoch": int(metrics.get("epoch", 0)),
            "totalEpochs": total,
            "trainLoss": metrics.get("train_loss"),
            "valLoss": metrics.get("val_loss"),
            "valAccuracy": metrics.get("val_accuracy"),
        },
    }
