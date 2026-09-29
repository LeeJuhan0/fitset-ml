from datetime import datetime, timezone

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.deployment import utils
from app.deployment.exceptions import NoTrainingHistoryError, VersionNotFoundError
from app.deployment.repository import add_deployment, latest_deployments
from app.deployment.schemas import DeployEnv, DeployResponse, InternalModelsResponse


async def deploy(s: AsyncSession, platform: str, version: str, env: DeployEnv) -> DeployResponse:
    """지정 버전 환경별 배포 이력 기록, 롤백 겸용"""
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

    bucket, key = utils.model_url(platform, version).removeprefix("s3://").split("/", 1)
    await add_deployment(s, platform, env, kind="classifier", version=version, bucket=bucket, model_key=key)

    return DeployResponse(
        deployed_version=version,
        platform=platform,
        env=env,
        deployed_at=datetime.now(timezone.utc).isoformat(),
    )


async def internal_latest(s: AsyncSession, platform: str, env: DeployEnv) -> InternalModelsResponse:
    """환경별 분류, 종목별 렙카운팅 최신 배포"""
    rows = await latest_deployments(s, platform, env)
    classifier = next((r for r in rows if r.kind == "classifier"), None)
    phases = sorted((r for r in rows if r.kind == "phase"), key=lambda r: r.class_name)
    return InternalModelsResponse(
        env=env,
        classifier=utils.internal_item(classifier, settings.class_mapping_url) if classifier else None,
        phase_models=[utils.internal_phase_item(r) for r in phases],
    )
