# Файл: app/config.py
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: SecretStr
    owner_chat_id: int  # Telegram ID владельца (для авторизации, управления и уведомлений)
    database_url: SecretStr  # Например: postgresql+asyncpg://user:pass@db:5432/jobhunter

    hh_access_token: SecretStr
    hh_resume_id: str

    search_query: str = "Оператор чата OR Менеджер OR Поддержка"
    poll_interval_seconds: int = 300
    default_cover_letter: str = (
        "Здравствуйте! Заинтересовала ваша вакансия. Буду рад обсудить детали."
    )

    @property
    def telegram_chat_id(self) -> int:
        """Алиас для обратной совместимости с кодом нотификатора."""
        return self.owner_chat_id

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )