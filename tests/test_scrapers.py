"""Тесты скрапинг-клиентов: HabrCareerClient, AvitoJobClient, FreelanceRuClient, WorkzillaClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.adapters.scrapers import (
    AvitoJobClient,
    FreelanceRuClient,
    HabrCareerClient,
    WorkzillaClient,
)
from app.core.job_hunter import WorkSchedule


def _mock_transport(
    handler: httpx._transports.base.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """Создаёт httpx.AsyncClient с мок-транспортом."""

    async def default_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html></html>")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler or default_handler))


# ────────────────────────────────────────────────
#  HabrCareerClient
# ────────────────────────────────────────────────


HABR_HTML = """
<html><body>
<div class="vacancy-card">
    <a class="vacancy-card__title-link" href="/vacancies/1001001">Python Developer</a>
    <a class="vacancy-card__company-title">Яндекс</a>
    <div class="vacancy-card__salary">от 200 000 ₽</div>
    <div class="vacancy-card__skills">Python, FastAPI, PostgreSQL</div>
</div>
<div class="vacancy-card">
    <a class="vacancy-card__title-link" href="/vacancies/1001002">Go Developer</a>
    <div class="vacancy-card__skills">Go, gRPC</div>
</div>
</body></html>
"""


class TestHabrCareerClient:
    """Тесты парсинга HTML Хабр Карьеры."""

    pytestmark = pytest.mark.asyncio(loop_scope="function")

    async def test_fetch_vacancies_parses_cards(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert "career.habr.com" in str(request.url)
            assert "q=" in str(request.url)
            return httpx.Response(200, text=HABR_HTML)

        async with _mock_transport(handler) as http_client:
            client = HabrCareerClient(http_client=http_client)
            vacancies = await client.fetch_vacancies("python", remote_only=True)

        assert len(vacancies) == 2
        assert vacancies[0].external_id == "1001001"
        assert vacancies[0].platform == "habr"
        assert vacancies[0].title == "Python Developer"
        assert vacancies[0].company == "Яндекс"
        assert vacancies[0].salary == "от 200 000 ₽"
        assert "Python" in vacancies[0].description

        assert vacancies[1].external_id == "1001002"
        assert vacancies[1].company is None
        assert vacancies[1].salary is None

    async def test_fetch_vacancies_empty_html(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html><body></body></html>")

        async with _mock_transport(handler) as http_client:
            client = HabrCareerClient(http_client=http_client)
            vacancies = await client.fetch_vacancies("ничего")

        assert vacancies == []

    async def test_fetch_vacancies_handles_http_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="Service Unavailable")

        async with _mock_transport(handler) as http_client:
            client = HabrCareerClient(http_client=http_client)
            vacancies = await client.fetch_vacancies("python")

        assert vacancies == []

    async def test_apply_always_returns_false(self) -> None:
        async with _mock_transport() as http_client:
            client = HabrCareerClient(http_client=http_client)
            result = await client.apply_to_vacancy("123", "Cover")

        assert result.ok is False
        assert "авто-отклик невозможен" in (result.reason or "")

    async def test_fetch_invitations_returns_empty(self) -> None:
        async with _mock_transport() as http_client:
            client = HabrCareerClient(http_client=http_client)
            invitations = await client.fetch_invitations()

        assert invitations == []


# ────────────────────────────────────────────────
#  AvitoJobClient
# ────────────────────────────────────────────────


AVITO_HTML = """
<html><body>
<div data-marker="item">
    <h3 itemprop="name">Менеджер по продажам</h3>
    <a itemprop="url" href="/rossiya/vakansii/menedzher_po_prodazham-_123456789">Link</a>
    <span itemprop="price">от 50 000 ₽</span>
    <div class="description">Опыт от 1 года</div>
</div>
<div data-marker="item">
    <h3 itemprop="name">Оператор call-центра</h3>
    <a itemprop="url" href="/rossiya/vakansii/operator-_987654321">Link</a>
</div>
</body></html>
"""


class TestAvitoJobClient:
    """Тесты парсинга HTML Авито Работа."""

    pytestmark = pytest.mark.asyncio(loop_scope="function")

    async def test_fetch_vacancies_parses_items(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=AVITO_HTML)

        async with _mock_transport(handler) as http_client:
            client = AvitoJobClient(http_client=http_client)
            vacancies = await client.fetch_vacancies("менеджер")

        assert len(vacancies) == 2
        assert vacancies[0].external_id == "123456789"
        assert vacancies[0].platform == "avito"
        assert vacancies[0].title == "Менеджер по продажам"
        assert vacancies[0].salary == "от 50 000 ₽"
        assert "Опыт" in vacancies[0].description

        assert vacancies[1].external_id == "987654321"

    async def test_fetch_vacancies_handles_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="Forbidden")

        async with _mock_transport(handler) as http_client:
            client = AvitoJobClient(http_client=http_client)
            vacancies = await client.fetch_vacancies("python")

        assert vacancies == []

    async def test_apply_always_returns_false(self) -> None:
        async with _mock_transport() as http_client:
            client = AvitoJobClient(http_client=http_client)
            result = await client.apply_to_vacancy("123", "Cover")

        assert result.ok is False
        assert "авто-отклик невозможен" in (result.reason or "")


# ────────────────────────────────────────────────
#  FreelanceRuClient
# ────────────────────────────────────────────────


FREELANCE_HTML = """
<html><body>
<div class="project">
    <a class="project__title" href="/projects/55555">Разработка бота Telegram</a>
    <span class="project__budget">15 000 ₽</span>
    <div class="project__description">Нужен бот для автоматизации</div>
</div>
</body></html>
"""


class TestFreelanceRuClient:
    """Тесты парсинга HTML Freelance.ru."""

    pytestmark = pytest.mark.asyncio(loop_scope="function")

    async def test_fetch_vacancies_parses_projects(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=FREELANCE_HTML)

        async with _mock_transport(handler) as http_client:
            client = FreelanceRuClient(http_client=http_client)
            vacancies = await client.fetch_vacancies("бот")

        assert len(vacancies) == 1
        assert vacancies[0].external_id == "55555"
        assert vacancies[0].platform == "freelance_ru"
        assert vacancies[0].title == "Разработка бота Telegram"
        assert vacancies[0].salary == "15 000 ₽"
        assert vacancies[0].schedule == WorkSchedule.REMOTE

    async def test_fetch_vacancies_empty_html(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html><body></body></html>")

        async with _mock_transport(handler) as http_client:
            client = FreelanceRuClient(http_client=http_client)
            vacancies = await client.fetch_vacancies("ничего")

        assert vacancies == []

    async def test_apply_always_returns_false(self) -> None:
        async with _mock_transport() as http_client:
            client = FreelanceRuClient(http_client=http_client)
            result = await client.apply_to_vacancy("123", "Cover")

        assert result.ok is False
        assert "авто-отклик невозможен" in (result.reason or "")


# ────────────────────────────────────────────────
#  WorkzillaClient
# ────────────────────────────────────────────────


WORKZILLA_HTML = """
<html><body>
<div class="task">
    <a class="task__title" href="/tasks/77777">Написать статью о Python</a>
    <span class="task__price">3 000 ₽</span>
    <div class="task__description">Нужна статья на 3000 слов</div>
</div>
</body></html>
"""


class TestWorkzillaClient:
    """Тесты парсинга HTML Workzilla."""

    pytestmark = pytest.mark.asyncio(loop_scope="function")

    async def test_fetch_vacancies_parses_tasks(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=WORKZILLA_HTML)

        async with _mock_transport(handler) as http_client:
            client = WorkzillaClient(http_client=http_client)
            with patch("app.adapters.scrapers.asyncio.sleep", new_callable=AsyncMock):
                vacancies = await client.fetch_vacancies("статья")

        assert len(vacancies) == 1
        assert vacancies[0].external_id == "77777"
        assert vacancies[0].platform == "workzilla"
        assert vacancies[0].title == "Написать статью о Python"
        assert vacancies[0].salary == "3 000 ₽"
        assert vacancies[0].schedule == WorkSchedule.REMOTE

    async def test_fetch_vacancies_handles_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="Too Many Requests")

        async with _mock_transport(handler) as http_client:
            client = WorkzillaClient(http_client=http_client)
            with patch("app.adapters.scrapers.asyncio.sleep", new_callable=AsyncMock):
                vacancies = await client.fetch_vacancies("python")

        assert vacancies == []

    async def test_apply_always_returns_false(self) -> None:
        async with _mock_transport() as http_client:
            client = WorkzillaClient(http_client=http_client)
            result = await client.apply_to_vacancy("123", "Cover")

        assert result.ok is False
        assert "авто-отклик невозможен" in (result.reason or "")
