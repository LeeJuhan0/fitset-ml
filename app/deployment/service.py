import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from app.deployment.schemas import DeployData, DeployRequest, ModelLatestData, VersionStatsData
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


def deploy(platform: str, payload: DeployRequest) -> DeployData:
    """지정 버전 latest.json 기록, 롤백 겸용"""
    version = payload.version
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

    return DeployData.model_validate({
        "deployedVersion": version,
        "platform": platform,
        "deployedAt": deployed_at,
    })


def latest(platform: str, current_version: str | None) -> ModelLatestData:
    """최신 버전·서명 URL 반환, 버전 리포팅 기록"""
    latest_info = get_latest(platform)
    if not latest_info:
        raise NoDeployedModelError()

    if current_version:
        _reports[platform].append((time.time(), current_version))
        _prune(platform)

    latest_version = latest_info["version"]
    return ModelLatestData.model_validate({
        "latestVersion": latest_version,
        "modelUrl": generate_presigned_model_download_url(latest_info["modelUrl"]),
        "metaUrl": settings.class_mapping_url,
        "isUpToDate": current_version == latest_version,
    })


def version_stats(platform: str) -> VersionStatsData:
    """최근 24시간 윈도우의 버전 분포 집계 유스케이스"""
    latest_info = get_latest(platform)
    latest_version = latest_info["version"] if latest_info else None

    _prune(platform)
    counts = utils.aggregate_reports(_reports[platform], time.time())
    total = sum(counts.values()) or 1

    return VersionStatsData.model_validate({
        "latestVersion": latest_version,
        "totalReports": sum(counts.values()),
        "stats": [
            {"version": v, "count": c, "ratio": round(c / total, 2)}
            for v, c in counts.most_common()
        ],
    })
