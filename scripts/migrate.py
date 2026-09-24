import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core import db

BASELINE = "3513cabd672e"
ALEMBIC_INI = "alembic.ini"


def _table_names(connection) -> set[str]:
    """동기 커넥션으로 현재 테이블 이름 조회"""
    return set(inspect(connection).get_table_names())


async def _existing_tables() -> set[str]:
    """앱 DSN 으로 접속해 테이블 목록 조회"""
    engine = db.create_engine()
    async with engine.connect() as connection:
        names = await connection.run_sync(_table_names)
    await engine.dispose()
    return names


def main() -> None:
    """create_all 로 만든 기존 DB 는 초기 리비전 표시 후 최신까지 적용"""
    config = Config(ALEMBIC_INI)
    tables = asyncio.run(_existing_tables())
    if "platforms" in tables and "alembic_version" not in tables:
        command.stamp(config, BASELINE)
    command.upgrade(config, "head")


if __name__ == "__main__":
    main()
