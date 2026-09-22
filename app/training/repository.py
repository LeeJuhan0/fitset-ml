import re

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import s3
from app.core.models import Platform
from app.data.models import DatasetFile
from app.training import utils


async def uploaded_filenames(s: AsyncSession, platform: str) -> set[str]:
    """업로드 확정 파일명 집합, 학습 대상 검증"""
    rows = (await s.exec(
        select(DatasetFile.filename).join(Platform).where(Platform.name == platform, DatasetFile.uploaded.is_(True))
    )).all()
    return set(rows)


def list_model_versions(platform: str) -> list[str]:
    """models 버킷의 v버전 폴더 목록"""
    paginator = s3._client().get_paginator("list_objects_v2")
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
