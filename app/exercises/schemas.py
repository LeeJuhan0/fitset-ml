from app.core.models import ExerciseRead
from app.core.schemas import CamelModel


class ListExercisesData(CamelModel):
    """exercises 응답, 인덱스 순 마스터"""
    exercises: list[ExerciseRead]


class SeedData(CamelModel):
    """seed 응답, 출처, 추가 갱신 수"""
    source: str
    model_class_count: int | None = None
    added: int
    updated: int


class SeedQuery(CamelModel):
    """?source= 쿼리, s3://버킷/키 또는 https URL, 없으면 CLASS_MAPPING_URL"""
    source: str | None = None
