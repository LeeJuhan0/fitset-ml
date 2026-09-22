from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.schemas import ApiResponse
from app.core.security import check_basic_auth
from app.deps import DbSessionDep, get_trace_id
from app.exercises import service
from app.exercises.schemas import ListExercisesData, SeedData, SeedQuery

router = APIRouter(tags=["exercises"], dependencies=[Depends(check_basic_auth)])


@router.get("/exercises", response_model=ApiResponse[ListExercisesData])
async def list_exercises(session: DbSessionDep, trace_id: str = Depends(get_trace_id)):
    """마스터 전체 목록"""
    return ApiResponse(trace_id=trace_id, data=await service.exercises(session))


@router.post("/exercises/seed", response_model=ApiResponse[SeedData])
async def seed(
    session: DbSessionDep,
    query: Annotated[SeedQuery, Query()],
    trace_id: str = Depends(get_trace_id),
):
    """class-mapping.json 으로 마스터 upsert"""
    return ApiResponse(trace_id=trace_id, data=await service.seed(session, query))
