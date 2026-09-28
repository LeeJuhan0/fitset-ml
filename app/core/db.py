import asyncio
import atexit
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from .config import settings

DSN = settings.database_url  # alembic env.py 용, 앱 엔진은 호출 시점 settings 를 읽는다

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None
_loop: asyncio.AbstractEventLoop | None = None


def register_models() -> None:
    """엔티티 모듈 import, 문자열 관계 해석용"""
    from app.core import models
    from app.data import models as data_models
    from app.deployment import models as deployment_models
    from app.labeling import models as labeling_models
    from app.phase import models as phase_models
    from app.training import models as training_models


def create_engine(dsn: str | None = None) -> AsyncEngine:
    """비동기 엔진 생성, pool_pre_ping, echo 끔"""
    register_models()
    return create_async_engine(dsn or settings.database_url, echo=False, pool_pre_ping=True)


def create_session(engine: AsyncEngine | None = None) -> async_sessionmaker:
    """세션 팩토리, expire_on_commit autoflush 끔"""
    return async_sessionmaker(engine or get_engine(), expire_on_commit=False, autoflush=False, class_=AsyncSession)


def get_engine() -> AsyncEngine:
    """엔진 싱글톤"""
    global _engine
    if _engine is None:
        _engine = create_engine()
    return _engine


def session_factory() -> async_sessionmaker:
    """세션 팩토리 싱글톤"""
    global _session_factory
    if _session_factory is None:
        _session_factory = create_session(get_engine())
    return _session_factory


def reset() -> None:
    """엔진·팩토리 폐기, 테스트 URL 교체용"""
    global _engine, _session_factory
    if _engine is not None:
        run(_engine.dispose())
    _engine = None
    _session_factory = None


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    """세션 컨텍스트, 정상 종료 commit, 예외 rollback"""
    async with session_factory()() as s:
        try:
            yield s
            await s.commit()
        except Exception:
            await s.rollback()
            raise


def run(coro):
    """워커·스크립트용, 프로세스 단일 루프, 풀 커넥션이 루프에 묶임"""
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        atexit.register(_dispose_at_exit)
    return _loop.run_until_complete(coro)


def _dispose_at_exit() -> None:
    """종료 시 같은 루프에서 풀 정리"""
    if _engine is not None and _loop is not None and not _loop.is_closed():
        _loop.run_until_complete(_engine.dispose())
