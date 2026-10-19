"""Тесты моделей БД, репозиториев и настроек."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from app.config import Settings
from app.db.models import (
    ITEM_TYPE_INVITATION,
    ITEM_TYPE_OFFERED,
    ITEM_TYPE_VACANCY,
    ProcessedItemRepository,
    UserSettings,
    UserSettingsRepository,
)


class TestConfigOwnerChatId:
    """Проверка обязательности OWNER_CHAT_ID в конфигурации."""

    def test_missing_owner_chat_id_raises_validation_error(self) -> None:
        """Если OWNER_CHAT_ID не передан, Settings не должен инициализироваться."""
        with pytest.raises(ValidationError):
            Settings(  # type: ignore[call-arg]
                _env_file=None,
                bot_token="fake:token",
                telegram_chat_id=123,
                database_url="postgresql+asyncpg://u:p@db/db",
                hh_access_token="fake_token",
                hh_resume_id="fake_resume",
                # owner_chat_id намеренно не передан
            )

    def test_owner_chat_id_parsed(self) -> None:
        cfg = Settings(  # type: ignore[call-arg]
            _env_file=None,
            bot_token="fake:token",
            telegram_chat_id=123,
            owner_chat_id=456,
            database_url="postgresql+asyncpg://u:p@db/db",
            hh_access_token="fake_token",
            hh_resume_id="fake_resume",
        )
        assert cfg.owner_chat_id == 456


class TestItemTypeConstants:
    """Проверка строковых констант для типов элементов."""

    def test_constants_values(self) -> None:
        assert ITEM_TYPE_VACANCY == "vacancy"
        assert ITEM_TYPE_OFFERED == "vacancy_offered"
        assert ITEM_TYPE_INVITATION == "invitation"

    def test_offered_fits_in_db_column_limit(self) -> None:
        """item_type в ProcessedItem имеет String(16) — проверяем длину."""
        assert len(ITEM_TYPE_OFFERED) <= 16
        assert len(ITEM_TYPE_VACANCY) <= 16
        assert len(ITEM_TYPE_INVITATION) <= 16


class TestUserSettingsModel:
    """Тесты модели UserSettings."""

    def test_instantiation_with_kwargs(self) -> None:
        settings = UserSettings(
            chat_id=123456,
            is_auto_mode=True,
            is_active=True,
            remote_only=True,
            search_query="Python",
            required_keywords=["fastapi"],
            excluded_keywords=["1c"],
        )
        assert settings.chat_id == 123456
        assert settings.is_auto_mode is True
        assert settings.is_active is True
        assert settings.remote_only is True
        assert settings.search_query == "Python"
        assert settings.required_keywords == ["fastapi"]
        assert settings.excluded_keywords == ["1c"]


class TestProcessedItemRepository:
    """Тесты ProcessedItemRepository."""

    pytestmark = pytest.mark.asyncio(loop_scope="function")

    async def test_get_processed_ids(self) -> None:
        mock_session = AsyncMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = ["id1", "id2", "id1"]
        mock_session.scalars.return_value = mock_scalars

        repo = ProcessedItemRepository(mock_session)
        ids = await repo.get_processed_ids("hh", ITEM_TYPE_VACANCY)

        assert ids == {"id1", "id2"}
        mock_session.scalars.assert_called_once()

    async def test_is_processed_true(self) -> None:
        mock_session = AsyncMock()
        mock_session.scalar.return_value = 42

        repo = ProcessedItemRepository(mock_session)
        res = await repo.is_processed("hh", ITEM_TYPE_VACANCY, "123")
        assert res is True

    async def test_is_processed_false(self) -> None:
        mock_session = AsyncMock()
        mock_session.scalar.return_value = None

        repo = ProcessedItemRepository(mock_session)
        res = await repo.is_processed("hh", ITEM_TYPE_OFFERED, "999")
        assert res is False

    async def test_mark_as_processed_empty_list(self) -> None:
        mock_session = AsyncMock()
        repo = ProcessedItemRepository(mock_session)
        await repo.mark_as_processed("hh", ITEM_TYPE_VACANCY, [])

        mock_session.execute.assert_not_called()
        mock_session.commit.assert_not_called()

    async def test_mark_as_processed_executes_insert(self) -> None:
        mock_session = AsyncMock()
        repo = ProcessedItemRepository(mock_session)
        await repo.mark_as_processed("hh", ITEM_TYPE_OFFERED, ["v1", "v2"])

        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()


class TestUserSettingsRepository:
    """Тесты UserSettingsRepository."""

    pytestmark = pytest.mark.asyncio(loop_scope="function")

    async def test_get_existing(self) -> None:
        mock_session = AsyncMock()
        existing = UserSettings(chat_id=123, is_auto_mode=True)
        mock_session.scalar.return_value = existing

        repo = UserSettingsRepository(mock_session)
        result = await repo.get(123)

        assert result is existing

    async def test_get_or_create_creates_when_missing(self) -> None:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.scalar.return_value = None

        repo = UserSettingsRepository(mock_session)
        settings = await repo.get_or_create(
            chat_id=456,
            default_query="Python Junior",
            default_auto_mode=True,
            default_remote_only=True,
            default_required_keywords=["fastapi"],
            default_excluded_keywords=["1c"],
        )

        assert settings.chat_id == 456
        assert settings.search_query == "Python Junior"
        assert settings.is_auto_mode is True
        assert settings.remote_only is True
        assert settings.required_keywords == ["fastapi"]
        assert settings.excluded_keywords == ["1c"]
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.refresh.assert_called_once()

    async def test_get_or_create_returns_existing(self) -> None:
        mock_session = AsyncMock()
        existing = UserSettings(chat_id=789, search_query="DevOps")
        mock_session.scalar.return_value = existing

        repo = UserSettingsRepository(mock_session)
        settings = await repo.get_or_create(chat_id=789)

        assert settings is existing
        mock_session.add.assert_not_called()

    async def test_update_settings_valid(self) -> None:
        mock_session = AsyncMock()
        existing = UserSettings(chat_id=100, is_auto_mode=True, search_query="QA")
        mock_session.scalar.return_value = existing

        repo = UserSettingsRepository(mock_session)
        updated = await repo.update(
            chat_id=100,
            is_auto_mode=False,
            search_query="Golang",
        )

        assert updated.is_auto_mode is False
        assert updated.search_query == "Golang"
        mock_session.commit.assert_called_once()
        mock_session.refresh.assert_called_once()

    async def test_update_settings_invalid_field_raises_value_error(self) -> None:
        mock_session = AsyncMock()
        repo = UserSettingsRepository(mock_session)

        with pytest.raises(ValueError, match="Недопустимое поле настроек"):
            await repo.update(chat_id=100, non_existent_key="bad")

