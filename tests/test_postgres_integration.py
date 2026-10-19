"""Интеграционные тесты на реальном PostgreSQL.

Запуск:
    1. Запустить тестовую БД:
       docker compose -f docker-compose.test.yml up -d
    2. Установить переменную окружения:
       $env:TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/jobhunter_test"
    3. Выполнить тесты:
       uv run pytest -m integration
    4. Остановить БД:
       docker compose -f docker-compose.test.yml down -v
"""

from __future__ import annotations

import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings, settings_defaults_from_config
from app.db.models import (
    ITEM_TYPE_OFFERED,
    ITEM_TYPE_VACANCY,
    ProcessedItemRepository,
    UserSettingsRepository,
)

TEST_DB_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DB_URL,
        reason="TEST_DATABASE_URL не задан. Интеграционные тесты Postgres пропущены.",
    ),
]


def _get_alembic_config(db_url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.fixture
async def clean_db() -> None:
    """Очищает схему public перед тестом."""
    assert TEST_DB_URL is not None
    engine = create_async_engine(TEST_DB_URL, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE;"))
        await conn.execute(text("CREATE SCHEMA public;"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO postgres;"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO public;"))
    await engine.dispose()


class TestPostgresMigrationsAndRepositories:
    """Интеграционные тесты схемы БД и репозиториев на реальном PostgreSQL."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_migration_upgrade_downgrade_upgrade_chain(
        self, clean_db: None
    ) -> None:
        """Проверка цепочки: чистая БД -> upgrade -> downgrade -1 -> upgrade."""
        assert TEST_DB_URL is not None
        alembic_cfg = _get_alembic_config(TEST_DB_URL)

        # 1. Накат до актуальной версии (001 + 002)
        command.upgrade(alembic_cfg, "head")

        # 2. Откат последней миграции (002 -> 001)
        command.downgrade(alembic_cfg, "-1")

        # 3. Повторный накат до head
        command.upgrade(alembic_cfg, "head")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_legacy_db_upgrade_preserves_rows(self, clean_db: None) -> None:
        """Проверка безопасного апгрейда существующей legacy-БД без потери данных."""
        assert TEST_DB_URL is not None
        engine = create_async_engine(TEST_DB_URL, isolation_level="AUTOCOMMIT")

        # Имитируем старую БД, созданную create_all
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE processed_items (
                        id SERIAL PRIMARY KEY,
                        platform VARCHAR(32) NOT NULL,
                        item_type VARCHAR(16) NOT NULL,
                        external_id VARCHAR(128) NOT NULL,
                        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
                        CONSTRAINT uq_platform_item
                            UNIQUE (platform, item_type, external_id)
                    );
                    INSERT INTO processed_items (platform, item_type, external_id)
                    VALUES
                        ('hh', 'vacancy', 'vac_legacy_1'),
                        ('hh', 'vacancy', 'vac_legacy_2'),
                        ('zarplata', 'invitation', 'inv_legacy_1');
                    """
                )
            )
        await engine.dispose()

        alembic_cfg = _get_alembic_config(TEST_DB_URL)

        # Накат head на legacy-БД без предварительного alembic stamp
        command.upgrade(alembic_cfg, "head")

        # Проверяем, что строки на месте
        engine_check = create_async_engine(TEST_DB_URL)
        async with engine_check.connect() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM processed_items;"))
            count = result.scalar()
            assert count == 3

            # Откат 002 -> 001
            command.downgrade(alembic_cfg, "-1")

            # В 001 downgrade() не удаляет processed_items — данные сохранены
            result_after_downgrade = await conn.execute(
                text("SELECT COUNT(*) FROM processed_items;")
            )
            assert result_after_downgrade.scalar() == 3

        await engine_check.dispose()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_user_settings_lifecycle_and_json_persistence(
        self, clean_db: None
    ) -> None:
        """Проверка get_or_create, update и десериализации JSON в list."""
        assert TEST_DB_URL is not None
        alembic_cfg = _get_alembic_config(TEST_DB_URL)
        command.upgrade(alembic_cfg, "head")

        engine = create_async_engine(TEST_DB_URL)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        cfg = Settings(  # type: ignore[call-arg]
            _env_file=None,
            bot_token="test:token",
            owner_chat_id=11223344,
            database_url=TEST_DB_URL,
            hh_access_token="fake_token",
            hh_resume_id="fake_resume",
            search_query="Python Backend Developer",
            remote_only=True,
            required_keywords=["fastapi", "asyncio"],
            excluded_keywords=["1c", "bitrix"],
        )

        async with session_factory() as session:
            repo = UserSettingsRepository(session)
            settings = await repo.get_or_create(
                chat_id=cfg.owner_chat_id,
                **settings_defaults_from_config(cfg),
            )
            assert settings.chat_id == 11223344
            assert settings.search_query == "Python Backend Developer"
            assert isinstance(settings.required_keywords, list)
            assert settings.required_keywords == ["fastapi", "asyncio"]
            assert isinstance(settings.excluded_keywords, list)
            assert settings.excluded_keywords == ["1c", "bitrix"]

            # Обновление настроек
            updated = await repo.update(
                chat_id=cfg.owner_chat_id,
                is_auto_mode=False,
                search_query="Golang Developer",
            )
            assert updated.is_auto_mode is False
            assert updated.search_query == "Golang Developer"

        # Проверка чтения из новой сессии
        async with session_factory() as session:
            repo = UserSettingsRepository(session)
            fresh = await repo.get(11223344)
            assert fresh is not None
            assert fresh.is_auto_mode is False
            assert fresh.search_query == "Golang Developer"
            assert fresh.required_keywords == ["fastapi", "asyncio"]

            # Повторный вызов get_or_create возвращает ту же запись
            same = await repo.get_or_create(
                chat_id=11223344,
                default_query="Different Query",
            )
            assert same.search_query == "Golang Developer"

        await engine.dispose()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_concurrent_get_or_create_race_condition(
        self, clean_db: None
    ) -> None:
        """Проверка отсутствия гонки: два параллельных вызова get_or_create."""
        assert TEST_DB_URL is not None
        alembic_cfg = _get_alembic_config(TEST_DB_URL)
        command.upgrade(alembic_cfg, "head")

        engine = create_async_engine(TEST_DB_URL)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async def _call_get_or_create(user_id: int) -> int:
            async with session_factory() as session:
                repo = UserSettingsRepository(session)
                res = await repo.get_or_create(
                    chat_id=user_id,
                    default_query="Python Concurrent",
                )
                return res.chat_id

        # Два параллельных вызова для одного chat_id
        res1, res2 = await asyncio.gather(
            _call_get_or_create(777),
            _call_get_or_create(777),
        )
        assert res1 == 777
        assert res2 == 777

        await engine.dispose()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_processed_items_mark_and_check(self, clean_db: None) -> None:
        """Проверка дедупликации mark_as_processed и is_processed."""
        assert TEST_DB_URL is not None
        alembic_cfg = _get_alembic_config(TEST_DB_URL)
        command.upgrade(alembic_cfg, "head")

        engine = create_async_engine(TEST_DB_URL)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with session_factory() as session:
            repo = ProcessedItemRepository(session)
            await repo.mark_as_processed(
                "hh", ITEM_TYPE_OFFERED, ["vac_101", "vac_102"]
            )

            assert await repo.is_processed("hh", ITEM_TYPE_OFFERED, "vac_101") is True
            assert await repo.is_processed("hh", ITEM_TYPE_OFFERED, "vac_102") is True
            assert await repo.is_processed("hh", ITEM_TYPE_OFFERED, "vac_999") is False

            # Проверка, что vacancy и vacancy_offered независимы
            assert await repo.is_processed("hh", ITEM_TYPE_VACANCY, "vac_101") is False

            # Повторный вызов не падает по UniqueConstraint
            await repo.mark_as_processed(
                "hh", ITEM_TYPE_OFFERED, ["vac_101", "vac_102", "vac_103"]
            )
            assert await repo.is_processed("hh", ITEM_TYPE_OFFERED, "vac_103") is True

        await engine.dispose()
