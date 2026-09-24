import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from app.deployment.schemas import (
    DeployResponse,
    ModelLatestResponse,
    VersionStatItem,
    VersionStatsResponse,
)
from app.deployment.exceptions import NoDeployedModelError, NoTrainingHistoryError, VersionNotFoundError

from app.core.config import settings
from app.deployment import utils
from app.deployment.repository import (
    generate_presigned_model_download_url,
    get_latest,
    put_latest,
)

_reports: dict[str, deque] = defaultdict(deque)


def _prune(platform: str):
    """윈도우 밖 버전 리포트 제거"""
    now = time.time()
    q = _reports[platform]
    while q and not utils.is_active(q[0][0], now):
        q.popleft()


def deploy(platform: str, version: str) -> DeployResponse:
    """지정 버전 latest.json 기록, 롤백 겸용"""
    import mlflow

    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()

    experiment = client.get_experiment_by_name(f"fitset-{platform}")
    if not experiment:
        raise NoTrainingHistoryError()

    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        filter_string=f"tags.mlflow.runName = '{version}'",
    )
    if not runs:
        raise VersionNotFoundError(version)

    run = runs[0]
    deployed_at = datetime.now(timezone.utc).isoformat()
    put_latest(platform, {
        "version": version,
        "modelUrl": utils.model_url(platform, version),
        "deployedAt": deployed_at,
        "mlflowRunId": run.info.run_id,
    })

    return DeployResponse(
        deployed_version=version,
        platform=platform,
        deployed_at=deployed_at,
    )


def latest(platform: str, current_version: str | None) -> ModelLatestResponse:
    """최신 버전·서명 URL 반환, 버전 리포팅 기록"""
    latest_info = get_latest(platform)
    if not latest_info:
        raise NoDeployedModelError()

    if current_version:
        _reports[platform].append((time.time(), current_version))
        _prune(platform)

    latest_version = latest_info["version"]
    return ModelLatestResponse(
        latest_version=latest_version,
        model_url=generate_presigned_model_download_url(latest_info["modelUrl"]),
        meta_url=settings.class_mapping_url,
        is_up_to_date=current_version == latest_version,
    )


def version_stats(platform: str) -> VersionStatsResponse:
    """최근 24시간 윈도우의 버전 분포 집계 유스케이스"""
    latest_info = get_latest(platform)
    latest_version = latest_info["version"] if latest_info else None

    _prune(platform)
    counts = utils.aggregate_reports(_reports[platform], time.time())
    total = sum(counts.values()) or 1

    return VersionStatsResponse(
        latest_version=latest_version,
        total_reports=sum(counts.values()),
        stats=[
            VersionStatItem(version=v, count=c, ratio=round(c / total, 2))
            for v, c in counts.most_common()
        ],
    )
