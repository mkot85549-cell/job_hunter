import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field

TG_HANDLE_PATTERN = re.compile(
    r"(?:(?<![a-zA-Z0-9._%+-])@|(?:https?://)?(?:t\.me|telegram\.me)/)([a-zA-Z0-9_]{5,32})\b",
    re.IGNORECASE,
)


@dataclass(slots=True, frozen=True)
class ApplyResult:
    """Результат отклика на вакансию."""

    ok: bool
    status_code: int
    reason: str | None = None

    def __bool__(self) -> bool:
        """Поддержка булевых проверок if result: для обратной совместимости."""
        return self.ok


class WorkSchedule(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    OFFICE = "office"


class Vacancy(BaseModel):
    external_id: str
    platform: str
    title: str
    description: str
    schedule: WorkSchedule
    url: str
    company: str | None = None
    salary: str | None = None


class Invitation(BaseModel):
    external_id: str
    vacancy_title: str
    vacancy_url: str
    message_text: str
    telegram_tags: list[str] = Field(default_factory=list)


class VacancyFilterCriteria(BaseModel):
    remote_only: bool = True
    required_keywords: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)


class JobPlatformClient(Protocol):
    async def fetch_vacancies(
        self, search_query: str, remote_only: bool = True
    ) -> list[Vacancy]:
        ...

    async def apply_to_vacancy(
        self, vacancy_id: str, cover_letter: str
    ) -> ApplyResult:
        ...

    async def fetch_invitations(self) -> list[Invitation]:
        ...



class NotificationSender(Protocol):
    async def send_invitation_alert(self, invitation: Invitation) -> None:
        ...


def extract_telegram_tags(text: str) -> list[str]:
    """Извлекает уникальные Telegram-теги из текста с сохранением порядка."""
    matches = TG_HANDLE_PATTERN.findall(text)
    unique_tags: dict[str, None] = {}
    for username in matches:
        normalized = f"@{username.lower()}"
        unique_tags[normalized] = None
    return list(unique_tags.keys())


def is_vacancy_suitable(
    vacancy: Vacancy,
    criteria: VacancyFilterCriteria,
) -> bool:
    """Проверяет вакансию на соответствие графику и ключевым словам."""
    full_text = f"{vacancy.title} {vacancy.description}".lower()

    if criteria.remote_only:
        is_marked_remote = vacancy.schedule == WorkSchedule.REMOTE
        mentions_remote = any(
            word in full_text for word in ("удаленно", "удалённо", "remote")
        )
        if not (is_marked_remote or mentions_remote):
            return False

    if criteria.excluded_keywords and any(
        word.lower() in full_text for word in criteria.excluded_keywords
    ):
        return False

    if criteria.required_keywords:
        return any(word.lower() in full_text for word in criteria.required_keywords)

    return True


class JobHunterService:
    def __init__(
        self,
        platform_client: JobPlatformClient,
        notifier: NotificationSender,
        criteria: VacancyFilterCriteria,
        cover_letter: str,
    ) -> None:
        self._client = platform_client
        self._notifier = notifier
        self._criteria = criteria
        self._cover_letter = cover_letter

    async def search_and_apply(
        self,
        search_query: str,
        already_applied_ids: set[str],
    ) -> list[str]:
        vacancies = await self._client.fetch_vacancies(search_query)
        applied_now: list[str] = []

        for vacancy in vacancies:
            if vacancy.external_id in already_applied_ids:
                continue
            if not is_vacancy_suitable(vacancy, self._criteria):
                continue

            success = await self._client.apply_to_vacancy(
                vacancy_id=vacancy.external_id,
                cover_letter=self._cover_letter,
            )
            if success:
                applied_now.append(vacancy.external_id)

        return applied_now

    async def process_invitations(
        self,
        already_notified_ids: set[str],
    ) -> list[Invitation]:
        invitations = await self._client.fetch_invitations()
        processed: list[Invitation] = []

        for invite in invitations:
            if invite.external_id in already_notified_ids:
                continue

            tags = extract_telegram_tags(invite.message_text)
            enriched_invite = invite.model_copy(update={"telegram_tags": tags})
            await self._notifier.send_invitation_alert(enriched_invite)
            processed.append(enriched_invite)

        return processed
