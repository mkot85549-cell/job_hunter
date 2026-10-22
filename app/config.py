# Файл: app/config.py
from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: SecretStr
    owner_chat_id: int = Field(
        validation_alias=AliasChoices(
            "OWNER_CHAT_ID",
            "TELEGRAM_CHAT_ID",
            "owner_chat_id",
            "telegram_chat_id",
        )
    )
    database_url: SecretStr  # Например: postgresql+asyncpg://user:pass@db:5432/jobhunter

    hh_access_token: SecretStr
    hh_resume_id: str

    # SuperJob (опционально)
    superjob_secret_key: SecretStr | None = None
    superjob_access_token: SecretStr | None = None
    superjob_resume_id: int | None = None

    # Переключатели площадок (через Telegram-команду /platforms или .env)
    enable_hh: bool = True
    enable_zarplata: bool = True
    enable_superjob: bool = False   # Требует отдельного API-ключа
    enable_habr: bool = False
    enable_avito: bool = False
    enable_freelance_ru: bool = False
    enable_workzilla: bool = False

    search_query: str = "Оператор чата OR Менеджер OR Поддержка"
    remote_only: bool = True
    required_keywords: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)

    poll_interval_seconds: int = 300
    default_cover_letter: str = (
        "Здравствуйте! Заинтересовала ваша вакансия. Буду рад обсудить детали."
    )

    @property
    def telegram_chat_id(self) -> int:
        """Алиас для обратной совместимости с кодом нотификатора."""
        return self.owner_chat_id

    @property
    def superjob_configured(self) -> bool:
        """Проверяет, заданы ли все обязательные поля SuperJob."""
        return (
            self.superjob_secret_key is not None
            and self.superjob_access_token is not None
            and self.superjob_resume_id is not None
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


def settings_defaults_from_config(config: Settings) -> dict[str, Any]:
    """Единый хелпер формирования дефолтных значений UserSettings из конфигурации."""
    return {
        "default_query": config.search_query,
        "default_auto_mode": True,
        "default_remote_only": config.remote_only,
        "default_required_keywords": list(config.required_keywords),
        "default_excluded_keywords": list(config.excluded_keywords),
    }