import asyncio
import json
import urllib.request

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import s3
from app.core.config import settings
from app.exercises.schemas import ListExercisesData, SeedData, SeedQuery
from app.exercises.repository import list_exercises, upsert_exercises


async def exercises(s: AsyncSession) -> ListExercisesData:
    """마스터 목록"""
    return ListExercisesData.model_validate({"exercises": await list_exercises(s)})


def load_mapping(source: str | None = None) -> dict:
    """매핑 JSON 읽기, s3:// 또는 http(s), 기본은 CLASS_MAPPING_URL"""
    src = source or settings.class_mapping_url
    if src.startswith("s3://"):
        bucket, key = src.removeprefix("s3://").split("/", 1)
        return json.loads(s3.get_object_bytes(bucket, key))
    with urllib.request.urlopen(src, timeout=10) as resp:
        return json.load(resp)


async def seed(s: AsyncSession, query: SeedQuery) -> SeedData:
    """매핑 JSON → exercises upsert"""
    source = query.source
    mapping = await asyncio.to_thread(load_mapping, source)
    result = await upsert_exercises(s, mapping["classes"])
    return SeedData.model_validate({"source": source or settings.class_mapping_url, "modelClassCount": mapping.get("modelClassCount"), **result})
