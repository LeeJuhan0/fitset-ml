from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.models import Platform, ensure_platform
from app.deployment.models import Environment, ModelDeployment, ensure_environment


async def add_deployment(s: AsyncSession, platform: str, env: str, **fields) -> None:
    """환경별 배포 이력 한 행 기록"""
    row = ModelDeployment(
        platform=await ensure_platform(s, platform),
        environment=await ensure_environment(s, env),
        **fields,
    )
    s.add(row)
    await s.flush()


async def latest_deployments(s: AsyncSession, platform: str, env: str) -> list[ModelDeployment]:
    """환경 안에서 종류와 종목별 가장 최근 배포 행"""
    rows = (await s.exec(
        select(ModelDeployment).join(Platform).join(Environment)
        .where(Platform.name == platform, Environment.name == env)
        .order_by(col(ModelDeployment.created_at).desc(), col(ModelDeployment.id).desc())
    )).all()
    latest: dict[tuple, ModelDeployment] = {}
    for r in rows:
        latest.setdefault((r.kind, r.class_name), r)
    return list(latest.values())
