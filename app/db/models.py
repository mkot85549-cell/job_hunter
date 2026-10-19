from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    String,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(AsyncAttrs, DeclarativeBase):
    pass


ITEM_TYPE_VACANCY = "vacancy"
ITEM_TYPE_OFFERED = "vacancy_offered"
ITEM_TYPE_INVITATION = "invitation"


class ProcessedItem(Base):
    __tablename__ = "processed_items"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "item_type",
            "external_id",
            name="uq_platform_item",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    # item_type: "vacancy", "vacancy_offered", "invitation"
    item_type: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


ALLOWED_USER_SETTINGS_FIELDS = {
    "is_auto_mode",
    "is_active",
    "search_query",
    "remote_only",
    "required_keywords",
    "excluded_keywords",
}


class UserSettings(Base):
    __tablename__ = "user_settings"

    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
    )
    is_auto_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    search_query: Mapped[str] = mapped_column(String(500), default="")
    remote_only: Mapped[bool] = mapped_column(Boolean, default=True)
    required_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    excluded_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProcessedItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_processed_ids(self, platform: str, item_type: str) -> set[str]:
        stmt = select(ProcessedItem.external_id).where(
            ProcessedItem.platform == platform,
            ProcessedItem.item_type == item_type,
        )
        result = await self._session.scalars(stmt)
        return set(result.all())

    async def is_processed(
        self,
        platform: str,
        item_type: str,
        external_id: str,
    ) -> bool:
        stmt = select(ProcessedItem.id).where(
            ProcessedItem.platform == platform,
            ProcessedItem.item_type == item_type,
            ProcessedItem.external_id == external_id,
        )
        result = await self._session.scalar(stmt)
        return result is not None

    async def mark_as_processed(
        self,
        platform: str,
        item_type: str,
        external_ids: list[str],
    ) -> None:
        if not external_ids:
            return
        values = [
            {"platform": platform, "item_type": item_type, "external_id": ext_id}
            for ext_id in external_ids
        ]
        stmt = insert(ProcessedItem).values(values).on_conflict_do_nothing(
            constraint="uq_platform_item"
        )
        await self._session.execute(stmt)
        await self._session.commit()


class UserSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, chat_id: int) -> UserSettings | None:
        stmt = select(UserSettings).where(UserSettings.chat_id == chat_id)
        return await self._session.scalar(stmt)

    async def get_or_create(
        self,
        chat_id: int,
        default_query: str,
        default_auto_mode: bool = True,
        default_remote_only: bool = True,
        default_required_keywords: list[str] | None = None,
        default_excluded_keywords: list[str] | None = None,
    ) -> UserSettings:
        if not default_query or not default_query.strip():
            raise ValueError("search_query не может быть пустым")

        # Атомарная вставка с игнорированием дубликата chat_id
        # во избежание состояния гонки
        stmt = (
            insert(UserSettings)
            .values(
                chat_id=chat_id,
                is_auto_mode=default_auto_mode,
                is_active=True,
                search_query=default_query.strip(),
                remote_only=default_remote_only,
                required_keywords=default_required_keywords or [],
                excluded_keywords=default_excluded_keywords or [],
            )
            .on_conflict_do_nothing(index_elements=["chat_id"])
        )
        await self._session.execute(stmt)
        await self._session.commit()

        settings = await self.get(chat_id)
        if settings is None:
            msg = f"Не удалось получить UserSettings для chat_id={chat_id}"
            raise RuntimeError(msg)
        return settings

    async def update(self, chat_id: int, **kwargs: Any) -> UserSettings:
        for key in kwargs:
            if key not in ALLOWED_USER_SETTINGS_FIELDS:
                raise ValueError(
                    f"Недопустимое поле настроек: '{key}'. "
                    f"Разрешенные поля: {sorted(ALLOWED_USER_SETTINGS_FIELDS)}"
                )

        if "search_query" in kwargs:
            val = kwargs["search_query"]
            if not isinstance(val, str) or not val.strip():
                raise ValueError("search_query не может быть пустым")
            kwargs["search_query"] = val.strip()

        settings = await self.get(chat_id)
        if settings is None:
            raise ValueError(
                f"Пользователь с chat_id={chat_id} не найден. "
                "Сначала вызовите get_or_create."
            )

        for key, value in kwargs.items():
            setattr(settings, key, value)
        await self._session.commit()
        await self._session.refresh(settings)
        return settings
