"""Тесты адаптеров: AiogramNotificationSender, HeadHunterClient, SuperJobClient."""

from __future__ import annotations

import html
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.adapters.platforms import HeadHunterClient, SuperJobClient
from app.adapters.telegram_notifier import AiogramNotificationSender
from app.core.job_hunter import Invitation, WorkSchedule


# ────────────────────────────────────────────────
#  AiogramNotificationSender
# ────────────────────────────────────────────────


class TestAiogramNotificationSender:
    """Тесты формирования и отправки Telegram-уведомлений."""

    pytestmark = pytest.mark.asyncio(loop_scope="function")

    @pytest.fixture()
    def mock_bot(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture()
    def notifier(self, mock_bot: AsyncMock) -> AiogramNotificationSender:
        return AiogramNotificationSender(bot=mock_bot, chat_id=123456)

    async def test_sends_message_to_correct_chat(
        self, notifier: AiogramNotificationSender, mock_bot: AsyncMock
    ) -> None:
        invite = Invitation(
            external_id="1",
            vacancy_title="Dev",
            vacancy_url="https://hh.ru/vacancy/1",
            message_text="Hello",
            telegram_tags=["@recruiter"],
        )
        await notifier.send_invitation_alert(invite)
        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 123456

    async def test_html_escapes_title(
        self, notifier: AiogramNotificationSender, mock_bot: AsyncMock
    ) -> None:
        """Спецсимволы в названии вакансии экранируются (защита от XSS)."""
        invite = Invitation(
            external_id="1",
            vacancy_title="Dev <script>alert('xss')</script>",
            vacancy_url="https://hh.ru/1",
            message_text="Msg",
        )
        await notifier.send_invitation_alert(invite)
        sent_text = mock_bot.send_message.call_args.kwargs["text"]
        assert "<script>" not in sent_text
        assert html.escape("Dev <script>alert('xss')</script>") in sent_text

    async def test_truncates_long_message(
        self, notifier: AiogramNotificationSender, mock_bot: AsyncMock
    ) -> None:
        """Текст приглашения обрезается до 1500 символов."""
        long_text = "A" * 3000
        invite = Invitation(
            external_id="1",
            vacancy_title="Dev",
            vacancy_url="https://hh.ru/1",
            message_text=long_text,
        )
        await notifier.send_invitation_alert(invite)
        sent_text = mock_bot.send_message.call_args.kwargs["text"]
        # Весь текст не должен быть включен
        assert long_text not in sent_text

    async def test_no_tags_shows_fallback_message(
        self, notifier: AiogramNotificationSender, mock_bot: AsyncMock
    ) -> None:
        invite = Invitation(
            external_id="1",
            vacancy_title="Dev",
            vacancy_url="https://hh.ru/1",
            message_text="Text",
            telegram_tags=[],
        )
        await notifier.send_invitation_alert(invite)
        sent_text = mock_bot.send_message.call_args.kwargs["text"]
        assert "Не найден автоматически" in sent_text

    async def test_tags_rendered_as_code(
        self, notifier: AiogramNotificationSender, mock_bot: AsyncMock
    ) -> None:
        invite = Invitation(
            external_id="1",
            vacancy_title="Dev",
            vacancy_url="https://hh.ru/1",
            message_text="Text",
            telegram_tags=["@recruiter", "@hr_lead"],
        )
        await notifier.send_invitation_alert(invite)
        sent_text = mock_bot.send_message.call_args.kwargs["text"]
        assert "<code>@recruiter</code>" in sent_text
        assert "<code>@hr_lead</code>" in sent_text

    async def test_disable_web_page_preview(
        self, notifier: AiogramNotificationSender, mock_bot: AsyncMock
    ) -> None:
        invite = Invitation(
            external_id="1",
            vacancy_title="Dev",
            vacancy_url="https://hh.ru/1",
            message_text="Text",
        )
        await notifier.send_invitation_alert(invite)
        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["disable_web_page_preview"] is True


# ────────────────────────────────────────────────
#  HeadHunterClient
# ────────────────────────────────────────────────


def _hh_transport(handler: httpx._transports.base.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """Создаёт httpx.AsyncClient с мок-транспортом."""

    async def default_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler or default_handler))


class TestHeadHunterClient:
    """Тесты парсинга ответов HH API."""

    pytestmark = pytest.mark.asyncio(loop_scope="function")

    async def test_fetch_vacancies_parses_items(self) -> None:
        api_response = {
            "items": [
                {
                    "id": "12345",
                    "name": "Python Developer",
                    "snippet": {
                        "requirement": "Знание Python",
                        "responsibility": "Писать код",
                    },
                    "alternate_url": "https://hh.ru/vacancy/12345",
                },
                {
                    "id": "67890",
                    "name": "Go Developer",
                    "snippet": None,
                    "alternate_url": "https://hh.ru/vacancy/67890",
                },
            ]
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            assert "/vacancies" in str(request.url)
            return httpx.Response(200, json=api_response)

        async with _hh_transport(handler) as http_client:
            client = HeadHunterClient(
                http_client=http_client,
                access_token="test-token",
                resume_id="resume-1",
            )
            vacancies = await client.fetch_vacancies("python")

        assert len(vacancies) == 2
        assert vacancies[0].external_id == "12345"
        assert vacancies[0].title == "Python Developer"
        assert vacancies[0].schedule == WorkSchedule.REMOTE
        assert "Знание Python" in vacancies[0].description
        # snippet=None — описание не падает
        assert vacancies[1].external_id == "67890"

    async def test_fetch_vacancies_empty_response(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"items": []})

        async with _hh_transport(handler) as http_client:
            client = HeadHunterClient(
                http_client=http_client,
                access_token="test-token",
                resume_id="resume-1",
            )
            vacancies = await client.fetch_vacancies("query")

        assert vacancies == []

    async def test_apply_to_vacancy_returns_true_on_201(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert "/negotiations" in str(request.url)
            return httpx.Response(201)

        async with _hh_transport(handler) as http_client:
            client = HeadHunterClient(
                http_client=http_client,
                access_token="test-token",
                resume_id="resume-1",
            )
            with patch("app.adapters.platforms.asyncio.sleep", new_callable=AsyncMock):
                result = await client.apply_to_vacancy("123", "Cover letter")

        assert result is True

    async def test_apply_to_vacancy_returns_false_on_409(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(409)

        async with _hh_transport(handler) as http_client:
            client = HeadHunterClient(
                http_client=http_client,
                access_token="test-token",
                resume_id="resume-1",
            )
            with patch("app.adapters.platforms.asyncio.sleep", new_callable=AsyncMock):
                result = await client.apply_to_vacancy("123", "Cover letter")

        assert result is False

    async def test_fetch_invitations_parses_messages(self) -> None:
        negotiations_response = {
            "items": [
                {
                    "id": "neg-1",
                    "vacancy": {
                        "name": "DevOps",
                        "alternate_url": "https://hh.ru/vacancy/99",
                    },
                }
            ]
        }
        messages_response = {
            "items": [
                {"text": "Здравствуйте, @recruiter_tg"},
                {"text": "Ждём вас!"},
            ]
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/negotiations/neg-1/messages" in url:
                return httpx.Response(200, json=messages_response)
            if "/negotiations" in url:
                return httpx.Response(200, json=negotiations_response)
            return httpx.Response(404)

        async with _hh_transport(handler) as http_client:
            client = HeadHunterClient(
                http_client=http_client,
                access_token="test-token",
                resume_id="resume-1",
            )
            invitations = await client.fetch_invitations()

        assert len(invitations) == 1
        assert invitations[0].external_id == "neg-1"
        assert invitations[0].vacancy_title == "DevOps"
        assert "recruiter_tg" in invitations[0].message_text

    async def test_fetch_invitations_skips_on_message_error(self) -> None:
        """Если сообщения не загрузились (!=200), приглашение пропускается."""
        negotiations_response = {
            "items": [
                {
                    "id": "neg-1",
                    "vacancy": {"name": "Dev", "alternate_url": ""},
                }
            ]
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/messages" in url:
                return httpx.Response(500)
            return httpx.Response(200, json=negotiations_response)

        async with _hh_transport(handler) as http_client:
            client = HeadHunterClient(
                http_client=http_client,
                access_token="test-token",
                resume_id="resume-1",
            )
            invitations = await client.fetch_invitations()

        assert invitations == []


# ────────────────────────────────────────────────
#  SuperJobClient
# ────────────────────────────────────────────────


class TestSuperJobClient:
    """Тесты парсинга ответов SuperJob API."""

    pytestmark = pytest.mark.asyncio(loop_scope="function")

    async def test_fetch_vacancies_parses_objects(self) -> None:
        api_response = {
            "objects": [
                {
                    "id": 111,
                    "profession": "Менеджер",
                    "candidat": "Требуется опыт от 1 года",
                    "link": "https://superjob.ru/vacancy/111",
                },
            ]
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=api_response)

        async with _hh_transport(handler) as http_client:
            client = SuperJobClient(
                http_client=http_client,
                secret_key="key",
                access_token="token",
                resume_id=42,
            )
            vacancies = await client.fetch_vacancies("менеджер")

        assert len(vacancies) == 1
        assert vacancies[0].external_id == "111"
        assert vacancies[0].platform == "superjob"
        assert vacancies[0].title == "Менеджер"

    async def test_apply_returns_true_on_200(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        async with _hh_transport(handler) as http_client:
            client = SuperJobClient(
                http_client=http_client,
                secret_key="key",
                access_token="token",
                resume_id=42,
            )
            with patch("app.adapters.platforms.asyncio.sleep", new_callable=AsyncMock):
                result = await client.apply_to_vacancy("111", "Cover")

        assert result is True

    async def test_apply_returns_false_on_403(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403)

        async with _hh_transport(handler) as http_client:
            client = SuperJobClient(
                http_client=http_client,
                secret_key="key",
                access_token="token",
                resume_id=42,
            )
            with patch("app.adapters.platforms.asyncio.sleep", new_callable=AsyncMock):
                result = await client.apply_to_vacancy("111", "Cover")

        assert result is False

    async def test_fetch_invitations_parses_objects(self) -> None:
        api_response = {
            "objects": [
                {
                    "id": 555,
                    "profession": "Аналитик",
                    "link": "https://superjob.ru/555",
                    "text": "Мы заинтересованы в вашем резюме",
                },
            ]
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=api_response)

        async with _hh_transport(handler) as http_client:
            client = SuperJobClient(
                http_client=http_client,
                secret_key="key",
                access_token="token",
                resume_id=42,
            )
            invitations = await client.fetch_invitations()

        assert len(invitations) == 1
        assert invitations[0].external_id == "555"
        assert invitations[0].vacancy_title == "Аналитик"
