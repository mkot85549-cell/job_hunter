"""Тесты бизнес-логики: extract_telegram_tags, is_vacancy_suitable, JobHunterService."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.job_hunter import (
    Invitation,
    JobHunterService,
    Vacancy,
    VacancyFilterCriteria,
    WorkSchedule,
    extract_telegram_tags,
    is_vacancy_suitable,
)

# ────────────────────────────────────────────────
#  Фабрики
# ────────────────────────────────────────────────


def _make_vacancy(
    *,
    external_id: str = "1",
    title: str = "Оператор чата",
    description: str = "Описание",
    schedule: WorkSchedule = WorkSchedule.REMOTE,
    url: str = "https://hh.ru/vacancy/1",
) -> Vacancy:
    return Vacancy(
        external_id=external_id,
        platform="hh",
        title=title,
        description=description,
        schedule=schedule,
        url=url,
    )


def _make_invitation(
    *,
    external_id: str = "inv-1",
    vacancy_title: str = "Менеджер",
    vacancy_url: str = "https://hh.ru/vacancy/42",
    message_text: str = "Текст без тегов",
) -> Invitation:
    return Invitation(
        external_id=external_id,
        vacancy_title=vacancy_title,
        vacancy_url=vacancy_url,
        message_text=message_text,
    )


# ────────────────────────────────────────────────
#  extract_telegram_tags
# ────────────────────────────────────────────────


class TestExtractTelegramTags:
    """Тесты парсинга Telegram-хэндлов из текстов приглашений."""

    def test_at_sign_handle(self) -> None:
        assert extract_telegram_tags("Пишите @recruiter_hh") == ["@recruiter_hh"]

    def test_t_me_link(self) -> None:
        assert extract_telegram_tags("https://t.me/some_recruiter") == [
            "@some_recruiter"
        ]

    def test_telegram_me_link(self) -> None:
        assert extract_telegram_tags("https://telegram.me/MyHandle") == ["@myhandle"]

    def test_http_without_https(self) -> None:
        assert extract_telegram_tags("http://t.me/user_test") == ["@user_test"]

    def test_multiple_unique_tags(self) -> None:
        text = "Контакт: @hr_anna, также @Dev_Lead. Ссылка: https://t.me/hr_anna"
        result = extract_telegram_tags(text)
        # @hr_anna дважды, но в результате должна быть одна копия
        assert result == ["@hr_anna", "@dev_lead"]

    def test_no_tags(self) -> None:
        assert extract_telegram_tags("Просто текст без ссылок") == []

    def test_empty_string(self) -> None:
        assert extract_telegram_tags("") == []

    def test_short_handle_ignored(self) -> None:
        """Хэндлы короче 5 символов не валидны в Telegram."""
        assert extract_telegram_tags("@abc") == []

    def test_email_not_captured(self) -> None:
        """Почта user@domain не должна захватываться как тег."""
        assert extract_telegram_tags("Пишите на user@company.com") == []

    def test_preserves_order(self) -> None:
        text = "@second_tag text @first_tag"
        result = extract_telegram_tags(text)
        assert result == ["@second_tag", "@first_tag"]

    def test_case_normalization(self) -> None:
        """Все теги приводятся к нижнему регистру."""
        tags = extract_telegram_tags("@MyHandle и https://t.me/MYHANDLE")
        assert tags == ["@myhandle"]


# ────────────────────────────────────────────────
#  is_vacancy_suitable
# ────────────────────────────────────────────────


class TestIsVacancySuitable:
    """Тесты фильтрации вакансий по критериям."""

    def test_remote_schedule_passes(self) -> None:
        vacancy = _make_vacancy(schedule=WorkSchedule.REMOTE)
        criteria = VacancyFilterCriteria(remote_only=True)
        assert is_vacancy_suitable(vacancy, criteria) is True

    def test_office_schedule_rejected_when_remote_only(self) -> None:
        vacancy = _make_vacancy(schedule=WorkSchedule.OFFICE)
        criteria = VacancyFilterCriteria(remote_only=True)
        assert is_vacancy_suitable(vacancy, criteria) is False

    def test_office_with_remote_keyword_in_description(self) -> None:
        """Даже если schedule=OFFICE, но в тексте есть 'удаленно' — пропускаем."""
        vacancy = _make_vacancy(
            schedule=WorkSchedule.OFFICE, description="Работа удаленно из дома"
        )
        criteria = VacancyFilterCriteria(remote_only=True)
        assert is_vacancy_suitable(vacancy, criteria) is True

    def test_office_with_remote_english_keyword(self) -> None:
        vacancy = _make_vacancy(
            schedule=WorkSchedule.OFFICE, description="Remote position"
        )
        criteria = VacancyFilterCriteria(remote_only=True)
        assert is_vacancy_suitable(vacancy, criteria) is True

    def test_remote_only_false_accepts_office(self) -> None:
        vacancy = _make_vacancy(schedule=WorkSchedule.OFFICE)
        criteria = VacancyFilterCriteria(remote_only=False)
        assert is_vacancy_suitable(vacancy, criteria) is True

    def test_excluded_keyword_rejects(self) -> None:
        vacancy = _make_vacancy(description="Нужен опыт в 1С")
        criteria = VacancyFilterCriteria(
            remote_only=False, excluded_keywords=["1С"]
        )
        assert is_vacancy_suitable(vacancy, criteria) is False

    def test_excluded_keyword_case_insensitive(self) -> None:
        vacancy = _make_vacancy(description="PHP developer")
        criteria = VacancyFilterCriteria(
            remote_only=False, excluded_keywords=["php"]
        )
        assert is_vacancy_suitable(vacancy, criteria) is False

    def test_required_keyword_present(self) -> None:
        vacancy = _make_vacancy(title="Python-разработчик")
        criteria = VacancyFilterCriteria(
            remote_only=False, required_keywords=["python"]
        )
        assert is_vacancy_suitable(vacancy, criteria) is True

    def test_required_keyword_absent(self) -> None:
        vacancy = _make_vacancy(title="Менеджер по продажам")
        criteria = VacancyFilterCriteria(
            remote_only=False, required_keywords=["python"]
        )
        assert is_vacancy_suitable(vacancy, criteria) is False

    def test_multiple_required_keywords_any_match(self) -> None:
        """Достаточно хотя бы одного совпадения из required_keywords."""
        vacancy = _make_vacancy(title="Go-разработчик")
        criteria = VacancyFilterCriteria(
            remote_only=False, required_keywords=["python", "go"]
        )
        assert is_vacancy_suitable(vacancy, criteria) is True

    def test_excluded_takes_priority_over_required(self) -> None:
        vacancy = _make_vacancy(title="Python-разработчик", description="1C интеграция")
        criteria = VacancyFilterCriteria(
            remote_only=False,
            required_keywords=["python"],
            excluded_keywords=["1c"],
        )
        assert is_vacancy_suitable(vacancy, criteria) is False

    def test_empty_criteria_accepts_everything(self) -> None:
        vacancy = _make_vacancy(schedule=WorkSchedule.OFFICE)
        criteria = VacancyFilterCriteria(remote_only=False)
        assert is_vacancy_suitable(vacancy, criteria) is True

    def test_keyword_found_in_title_not_only_description(self) -> None:
        """Ключевые слова ищутся в title + description."""
        vacancy = _make_vacancy(title="DevOps", description="CI/CD pipeline")
        criteria = VacancyFilterCriteria(
            remote_only=False, required_keywords=["devops"]
        )
        assert is_vacancy_suitable(vacancy, criteria) is True


# ────────────────────────────────────────────────
#  JobHunterService
# ────────────────────────────────────────────────


class TestJobHunterService:
    """Тесты сервиса search_and_apply / process_invitations."""

    pytestmark = pytest.mark.asyncio(loop_scope="function")

    @pytest.fixture()
    def mock_client(self) -> AsyncMock:
        client = AsyncMock()
        client.fetch_vacancies = AsyncMock(return_value=[])
        client.apply_to_vacancy = AsyncMock(return_value=True)
        client.fetch_invitations = AsyncMock(return_value=[])
        return client

    @pytest.fixture()
    def mock_notifier(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture()
    def criteria(self) -> VacancyFilterCriteria:
        return VacancyFilterCriteria(remote_only=False)

    @pytest.fixture()
    def service(
        self,
        mock_client: AsyncMock,
        mock_notifier: AsyncMock,
        criteria: VacancyFilterCriteria,
    ) -> JobHunterService:
        return JobHunterService(
            platform_client=mock_client,
            notifier=mock_notifier,
            criteria=criteria,
            cover_letter="Привет!",
        )

    # ── search_and_apply ──

    async def test_apply_new_vacancies(
        self, service: JobHunterService, mock_client: AsyncMock
    ) -> None:
        mock_client.fetch_vacancies.return_value = [
            _make_vacancy(external_id="v1"),
            _make_vacancy(external_id="v2"),
        ]
        result = await service.search_and_apply("query", already_applied_ids=set())
        assert result == ["v1", "v2"]
        assert mock_client.apply_to_vacancy.call_count == 2

    async def test_skip_already_applied(
        self, service: JobHunterService, mock_client: AsyncMock
    ) -> None:
        mock_client.fetch_vacancies.return_value = [
            _make_vacancy(external_id="v1"),
            _make_vacancy(external_id="v2"),
        ]
        result = await service.search_and_apply("query", already_applied_ids={"v1"})
        assert result == ["v2"]
        assert mock_client.apply_to_vacancy.call_count == 1

    async def test_filter_unsuitable_vacancies(
        self,
        mock_client: AsyncMock,
        mock_notifier: AsyncMock,
    ) -> None:
        """Вакансии не по criteria (remote_only + OFFICE) отбрасываются."""
        strict_criteria = VacancyFilterCriteria(remote_only=True)
        service = JobHunterService(
            platform_client=mock_client,
            notifier=mock_notifier,
            criteria=strict_criteria,
            cover_letter="Привет!",
        )
        mock_client.fetch_vacancies.return_value = [
            _make_vacancy(external_id="v1", schedule=WorkSchedule.OFFICE),
        ]
        result = await service.search_and_apply("query", already_applied_ids=set())
        assert result == []
        mock_client.apply_to_vacancy.assert_not_called()

    async def test_failed_apply_not_in_result(
        self, service: JobHunterService, mock_client: AsyncMock
    ) -> None:
        """Если API вернул False (отклик не прошёл) — ID не попадает в результат."""
        mock_client.fetch_vacancies.return_value = [_make_vacancy(external_id="v1")]
        mock_client.apply_to_vacancy.return_value = False
        result = await service.search_and_apply("query", already_applied_ids=set())
        assert result == []

    async def test_empty_vacancies_list(
        self, service: JobHunterService, mock_client: AsyncMock
    ) -> None:
        mock_client.fetch_vacancies.return_value = []
        result = await service.search_and_apply("query", already_applied_ids=set())
        assert result == []
        mock_client.apply_to_vacancy.assert_not_called()

    # ── process_invitations ──

    async def test_process_new_invitations(
        self,
        service: JobHunterService,
        mock_client: AsyncMock,
        mock_notifier: AsyncMock,
    ) -> None:
        mock_client.fetch_invitations.return_value = [
            _make_invitation(
                external_id="inv-1",
                message_text="Напишите @hr_recruiter для обсуждения",
            ),
        ]
        result = await service.process_invitations(already_notified_ids=set())
        assert len(result) == 1
        assert result[0].telegram_tags == ["@hr_recruiter"]
        mock_notifier.send_invitation_alert.assert_called_once()

    async def test_skip_already_notified(
        self,
        service: JobHunterService,
        mock_client: AsyncMock,
        mock_notifier: AsyncMock,
    ) -> None:
        mock_client.fetch_invitations.return_value = [
            _make_invitation(external_id="inv-1"),
        ]
        result = await service.process_invitations(already_notified_ids={"inv-1"})
        assert result == []
        mock_notifier.send_invitation_alert.assert_not_called()

    async def test_invitations_without_tags(
        self,
        service: JobHunterService,
        mock_client: AsyncMock,
        mock_notifier: AsyncMock,
    ) -> None:
        """Приглашения без TG-тегов всё равно отправляются в нотификатор."""
        mock_client.fetch_invitations.return_value = [
            _make_invitation(external_id="inv-1", message_text="Просто текст"),
        ]
        result = await service.process_invitations(already_notified_ids=set())
        assert len(result) == 1
        assert result[0].telegram_tags == []
        mock_notifier.send_invitation_alert.assert_called_once()

    async def test_multiple_invitations_order_preserved(
        self,
        service: JobHunterService,
        mock_client: AsyncMock,
        mock_notifier: AsyncMock,
    ) -> None:
        mock_client.fetch_invitations.return_value = [
            _make_invitation(external_id="inv-1"),
            _make_invitation(external_id="inv-2"),
            _make_invitation(external_id="inv-3"),
        ]
        result = await service.process_invitations(already_notified_ids=set())
        assert [r.external_id for r in result] == ["inv-1", "inv-2", "inv-3"]
        assert mock_notifier.send_invitation_alert.call_count == 3
