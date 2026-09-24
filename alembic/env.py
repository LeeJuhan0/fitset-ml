import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

from app.core.db import DSN, register_models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

register_models()
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """DB 접속 없이 SQL 스크립트만 출력"""
    context.configure(
        url=DSN or config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """동기 커넥션 위에서 마이그레이션 실행"""
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """앱과 같은 DSN 으로 비동기 엔진을 열어 마이그레이션 실행"""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = DSN

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
