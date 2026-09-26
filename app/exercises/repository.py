from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import CLASSES
from app.core.models import Exercise, ExerciseRead, find_exercise
from app.exercises.utils import class_folder
from app.motions.utils import load_motion


async def list_exercises(s: AsyncSession) -> list[ExerciseRead]:
    """마스터 전체, 인덱스 순"""
    rows = (await s.exec(select(Exercise).order_by(Exercise.index))).all()
    return [ExerciseRead.model_validate(r, from_attributes=True) for r in rows]


async def upsert_exercises(s: AsyncSession, items: list[dict]) -> dict:
    """class-mapping 항목 upsert, 판정 모듈 유무 반영, 추가 갱신 수"""
    added = updated = 0
    existing = {r.class_name: r for r in (await s.exec(select(Exercise))).all()}
    for it in items:
        values = dict(index=int(it["index"]), class_name=it["class"], slug=it["slug"], name=it["name"], exercise_id=it.get("exerciseId"))
        row = existing.get(it["class"])
        if row is None:
            row = Exercise(**values)
            added += 1
        if row.id is not None:
            for k, v in values.items():
                setattr(row, k, v)
            updated += 1
        row.phase_supported = load_motion(row.class_name) is not None
        s.add(row)
    return {"added": added, "updated": updated}


async def is_class_known(s: AsyncSession, class_name: str) -> bool:
    """마스터에 있거나 분류 CLASSES 에 있는 종목인지"""
    if class_name in CLASSES:
        return True
    return await find_exercise(s, class_name) is not None


async def folder_for(s: AsyncSession, class_name: str) -> str:
    """종목의 버킷 폴더명, 마스터 인덱스 우선, 없으면 CLASSES 순서"""
    row = await find_exercise(s, class_name)
    index = row.index if row is not None else CLASSES.index(class_name)
    return class_folder(index, class_name)
