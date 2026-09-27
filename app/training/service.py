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
from app.core.utils import LOST_PROCESS_ERROR, exit_error, read_tail
from app.training import utils
from app.training.repository import (
    add_training_run,
    finish_training_run,
    get_training_run,
    next_version,
    running_training_runs,
    training_errors,
    uploaded_filenames,
)

_procs: dict[str, subprocess.Popen] = {}


def _create_run(platform: str, version: str) -> tuple[str, str]:
    """MLflow experiment 확보, RUNNING run 생성, (experiment_id, run_id)"""
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()
    exp = client.get_experiment_by_name(f"fitset-{platform}")
    exp_id = client.create_experiment(f"fitset-{platform}") if exp is None else exp.experiment_id
    run = client.create_run(experiment_id=exp_id, run_name=version)
    return exp_id, run.info.run_id


def _log_path(platform: str, version: str) -> pathlib.Path:
    """trainer 로그 경로"""
    return pathlib.Path(tempfile.gettempdir()) / f"trainer_{platform}_{version}.log"


def _fail_mlflow_run(run_id: str, error: str) -> None:
    """RUNNING 으로 남은 MLflow run 을 FAILED 로, 사유 태그"""
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()
    if client.get_run(run_id).info.status != "RUNNING":
        return
    client.set_tag(run_id, "error", error[:5000])
    client.set_terminated(run_id, status="FAILED")


async def reconcile(s: AsyncSession, platform: str) -> None:
    """running 행의 프로세스 종료 판정, 죽었으면 failed 와 사유 기록"""
    for row in await running_training_runs(s, platform):
        proc = _procs.get(row.mlflow_run_id)
        if proc is not None and proc.poll() is None:
            continue
        _procs.pop(row.mlflow_run_id, None)
        if proc is not None and proc.returncode == 0:
            await finish_training_run(s, row, "completed")
            continue
        error = LOST_PROCESS_ERROR if proc is None else exit_error(proc.returncode, read_tail(_log_path(platform, row.version)))
        await finish_training_run(s, row, "failed", error)
        await asyncio.to_thread(_fail_mlflow_run, row.mlflow_run_id, error)
    await s.commit()


async def start_training(s: AsyncSession, platform: str, files: list[str], *, epochs: int, lr: float) -> TrainStartResponse:
    """파일 검증, 버전 채번, MLflow run 생성, 학습 기록, trainer spawn"""
    await reconcile(s, platform)
    if await running_training_runs(s, platform):
        raise TrainingAlreadyRunningError()

    valid = await uploaded_filenames(s, platform)
    invalid = [f for f in files if f not in valid]
    if invalid:
        raise UntrainableFilesError(invalid)

    version = await asyncio.to_thread(next_version, platform)
    exp_id, run_id = await asyncio.to_thread(_create_run, platform, version)

    log_file = open(_log_path(platform, version), "w")

    proc = subprocess.Popen(
        [
            sys.executable, "-u", "-m", "app.worker.trainer",
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

    _procs[run_id] = proc
    await add_training_run(s, platform, mlflow_run_id=run_id, version=version, epochs=epochs, lr=lr, num_files=len(files))

    return TrainStartResponse(job_id=run_id, experiment_id=exp_id, version=version, total_epochs=epochs)


async def get_status(s: AsyncSession, platform: str, job_id: str) -> TrainStatusResponse:
    """종료 판정 후 MLflow run 상태, 최신 메트릭, 실패 사유"""
    await reconcile(s, platform)
    row = await get_training_run(s, job_id)
    return await asyncio.to_thread(_status, job_id, row.epochs if row else 0, row.error if row else None)


def _status(job_id: str, total: int, error: str | None) -> TrainStatusResponse:
    """MLflow run 상태·최신 메트릭 조회"""
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()

    try:
        run = client.get_run(job_id)
    except Exception:
        raise JobNotFoundError()

    state = run.info.status
    metrics = run.data.metrics

    return TrainStatusResponse(
        status=utils.STATUS_MAP.get(state, state.lower()),
        experiment_id=run.info.experiment_id,
        epoch=int(metrics.get("epoch", 0)),
        total_epochs=total,
        train_loss=metrics.get("train_loss"),
        val_loss=metrics.get("val_loss"),
        val_accuracy=metrics.get("val_accuracy"),
        error=error or run.data.tags.get("error"),
    )


async def list_runs(s: AsyncSession, platform: str) -> RunsResponse:
    """종료 판정 후 run 목록, 실패 사유 병합"""
    await reconcile(s, platform)
    return await asyncio.to_thread(_runs, platform, await training_errors(s, platform))


def _runs(platform: str, errors: dict[str, str]) -> RunsResponse:
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
            error=errors.get(r.info.run_id) or r.data.tags.get("error"),
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
