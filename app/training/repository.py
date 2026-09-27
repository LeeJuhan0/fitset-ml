import re

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import s3
from app.core.models import Platform, ensure_platform
from app.core.utils import utcnow
from app.data.models import DatasetFile
from app.training import utils
from app.training.models import TrainingRun


async def uploaded_filenames(s: AsyncSession, platform: str) -> set[str]:
    """업로드 확정 파일명 집합, 학습 대상 검증"""
    rows = (await s.exec(
        select(DatasetFile.filename).join(Platform).where(Platform.name == platform, DatasetFile.uploaded.is_(True))
    )).all()
    return set(rows)


def list_model_versions(platform: str) -> list[str]:
    """models 버킷의 v버전 폴더 목록"""
    paginator = s3.client().get_paginator("list_objects_v2")
    pages = paginator.paginate(
        Bucket=s3.settings.models_bucket,
        Prefix=f"{platform}/",
        Delimiter="/",
    )
    versions = []
    for page in pages:
        for prefix in page.get("CommonPrefixes", []):
            name = prefix["Prefix"].rstrip("/").split("/")[-1]
            if re.match(r"v\d+\.\d+", name):
                versions.append(name)
    return sorted(versions, key=utils.version_key)


def next_version(platform: str) -> str:
    """다음 버전 채번"""
    return utils.bump_version(list_model_versions(platform))


async def add_training_run(s: AsyncSession, platform: str, **fields) -> None:
    """학습 시작 기록, running"""
    s.add(TrainingRun(platform=await ensure_platform(s, platform), **fields))
    await s.flush()


async def running_training_runs(s: AsyncSession, platform: str) -> list[TrainingRun]:
    """플랫폼의 running 학습 행"""
    return list((await s.exec(
        select(TrainingRun).join(Platform).where(Platform.name == platform, TrainingRun.status == "running")
    )).all())


async def get_training_run(s: AsyncSession, run_id: str) -> TrainingRun | None:
    """run id 로 학습 행 조회"""
    return (await s.exec(select(TrainingRun).where(TrainingRun.mlflow_run_id == run_id))).first()


async def finish_training_run(s: AsyncSession, row: TrainingRun, status: str, error: str | None = None) -> None:
    """종료 판정 기록, 상태 사유 시각"""
    row.status = status
    row.error = error
    row.finished_at = utcnow()
    s.add(row)
    await s.flush()


async def training_errors(s: AsyncSession, platform: str) -> dict[str, str]:
    """실패 run id 별 사유"""
    rows = (await s.exec(
        select(TrainingRun).join(Platform).where(Platform.name == platform, TrainingRun.error.is_not(None))
    )).all()
    return {r.mlflow_run_id: r.error for r in rows}
