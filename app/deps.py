from typing import Annotated, AsyncIterator

from fastapi import Depends, Path, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import db
from app.core.config import PLATFORMS
from app.core.exceptions import InvalidPlatformError


def get_trace_id(request: Request) -> str:
    """요청 state 의 traceId 반환"""
    return request.state.trace_id


def validate_platform(platform: str = Path(...)) -> str:
    """platform 경로값 검증, ios android"""
    if platform not in PLATFORMS:
        raise InvalidPlatformError()
    return platform


async def use_session() -> AsyncIterator[AsyncSession]:
    """요청 단위 세션, 응답 전 commit, 예외면 rollback"""
    async with db.session() as s:
        yield s


DbSessionDep = Annotated[AsyncSession, Depends(use_session)]
