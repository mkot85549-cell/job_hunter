"""Alembic env.py — async-миграции для PostgreSQL через asyncpg."""

import asyncio
from logging.config import fileConfig
import os
import sys

# Добавляем корень проекта в sys.path
sys.path.insert(0, os.path.abspath("."))

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import Settings
from app.db.models import Base

# ─── Конфигурация Alembic ────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Подставляем DATABASE_URL из .env / окружения
db_url = os.getenv("DATABASE_URL")
if not db_url:
    try:
        settings = Settings()  # type: ignore[call-arg]
        db_url = settings.database_url.get_secret_value()
    except Exception:
        db_url = config.get_main_option("sqlalchemy.url") or "postgresql+asyncpg://postgres:postgres@localhost:5432/jobhunter"

config.set_main_option("sqlalchemy.url", db_url)

# Метаданные моделей — Alembic сравнивает их со схемой БД
target_metadata = Base.metadata


# ─── Offline-режим (генерация SQL без подключения к БД) ───
def run_migrations_offline() -> None:
    """Генерирует SQL-скрипт миграции без подключения к базе."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


# ─── Online-режим (применение миграций к живой БД) ────────
def do_run_migrations(connection) -> None:  # noqa: ANN001
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Подключается к БД через asyncpg и применяет миграции."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Точка входа для online-миграций (async)."""
    asyncio.run(run_async_migrations())


# ─── Выбор режима ─────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
