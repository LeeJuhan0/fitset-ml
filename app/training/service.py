import asyncio
import subprocess
import sys
import json
import tempfile
import pathlib

import mlflow
from sqlmodel.ext.asyncio.session import AsyncSession
from app.training.schemas import (
    MetricHistoryResponse,
    MetricPoint,
    RunItem,
    RunMetrics,
    RunParams,
    RunsResponse,
    TrainStartResponse,
    TrainStatusResponse,
)
from app.training.exceptions import JobNotFoundError, TrainingAlreadyRunningError, UntrainableFilesError

from app.core.config import settings
from app.training import utils
from app.training.repository import next_version, uploaded_filenames

_running: dict[str, dict] = {}


def _create_run(platform: str, version: str) -> tuple[str, str]:
    """MLflow experiment 확보, RUNNING run 생성, (experiment_id, run_id)"""
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()
    exp = client.get_experiment_by_name(f"fitset-{platform}")
    exp_id = client.create_experiment(f"fitset-{platform}") if exp is None else exp.experiment_id
    run = client.create_run(experiment_id=exp_id, run_name=version)
    return exp_id, run.info.run_id


async def start_training(s: AsyncSession, platform: str, files: list[str], *, epochs: int, lr: float) -> TrainStartResponse:
    """파일 검증, 버전 채번, MLflow run 생성, trainer spawn"""
    if platform in _running and _running[platform]["process"].poll() is None:
        raise TrainingAlreadyRunningError()

    valid = await uploaded_filenames(s, platform)
    invalid = [f for f in files if f not in valid]
    if invalid:
        raise UntrainableFilesError(invalid)

    version = await asyncio.to_thread(next_version, platform)
    exp_id, run_id = await asyncio.to_thread(_create_run, platform, version)

    log_path = pathlib.Path(tempfile.gettempdir()) / f"trainer_{platform}_{version}.log"
    log_file = open(log_path, "w")

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "app.worker.trainer",
            "--platform", platform,
            "--files", json.dumps(files),
            "--epochs", str(epochs),
            "--lr", str(lr),
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
        "total_epochs": epochs,
    }

    return TrainStartResponse(job_id=run_id, experiment_id=exp_id, version=version, total_epochs=epochs)


def get_status(platform: str, job_id: str) -> TrainStatusResponse:
    """MLflow run 상태·최신 메트릭 조회 유스케이스"""
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()

    try:
        run = client.get_run(job_id)
    except Exception:
        raise JobNotFoundError()

    state = run.info.status
    metrics = run.data.metrics
    job = _running.get(platform, {})
    total = job.get("total_epochs", 0)

    return TrainStatusResponse(
        status=utils.STATUS_MAP.get(state, state.lower()),
        experiment_id=run.info.experiment_id,
        epoch=int(metrics.get("epoch", 0)),
        total_epochs=total,
        train_loss=metrics.get("train_loss"),
        val_loss=metrics.get("val_loss"),
        val_accuracy=metrics.get("val_accuracy"),
    )


def list_runs(platform: str) -> RunsResponse:
    """최근 50개 run 목록, best run 선정, MLflow 출처"""
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()

    exp = client.get_experiment_by_name(f"fitset-{platform}")
    if not exp:
        return RunsResponse(runs=[])

    raw = client.search_runs(
        experiment_ids=[exp.experiment_id],
        order_by=["start_time DESC"],
        max_results=50,
    )

    runs = []
    for r in raw:
        p = r.data.params
        m = r.data.metrics
        start_ms = r.info.start_time
        end_ms = r.info.end_time

        runs.append(RunItem(
            run_id=r.info.run_id,
            version=r.info.run_name,
            status=r.info.status,
            start_time=start_ms,
            end_time=end_ms,
            params=RunParams(
                epochs=int(p["epochs"]) if "epochs" in p else None,
                lr=float(p["lr"]) if "lr" in p else None,
                num_files=len(json.loads(p["files"])) if "files" in p else None,
            ),
            metrics=RunMetrics(
                train_loss=m.get("train_loss"),
                val_loss=m.get("val_loss"),
                val_accuracy=m.get("val_accuracy"),
                test_accuracy=m.get("test_accuracy"),
                f1Macro=m.get("f1_macro"),
                epoch=int(m.get("epoch", 0)),
            ),
        ))

    return RunsResponse(runs=runs, best_run_id=utils.pick_best_run(runs))


def metric_history(run_id: str, metric: str) -> MetricHistoryResponse:
    """특정 run의 메트릭 step별 시계열 조회"""
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()

    history = client.get_metric_history(run_id, metric)
    return MetricHistoryResponse(
        metric=metric,
        history=[MetricPoint(step=h.step, value=h.value) for h in history],
    )
