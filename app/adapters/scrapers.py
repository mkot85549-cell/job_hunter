"""Скрапинг-клиенты для площадок без публичного API.

Хабр Карьера  — JSON-эндпоинт (XHR) career.habr.com/vacancies
Авито Работа  — HTML-парсинг avito.ru/rossiya/vakansii
Freelance.ru  — HTML-парсинг freelance.ru/projects
Workzilla     — HTML-парсинг work-zilla.com/projects
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from app.core.job_hunter import ApplyResult, Invitation, Vacancy, WorkSchedule

logger = logging.getLogger(__name__)

# Общий User-Agent, имитирующий обычный браузер
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


# ────────────────────────────────────────────────
#  Хабр Карьера (career.habr.com)
# ────────────────────────────────────────────────


class HabrCareerClient:
    """Клиент Хабр Карьеры через полуофициальный XHR-эндпоинт.

    Возвращает HTML-фрагмент при заголовке ``X-Requested-With: XMLHttpRequest``.
    Авторизация не требуется для просмотра; авто-отклик невозможен.
    """

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http = http_client
        self._base_url = "https://career.habr.com"

    async def fetch_vacancies(
        self, search_query: str, remote_only: bool = True
    ) -> list[Vacancy]:
        params: dict[str, Any] = {
            "q": search_query,
            "type": "all",
            "sort": "date",
            "page": 1,
        }
        if remote_only:
            params["remote"] = "true"

        headers = {
            "User-Agent": _UA,
            "Accept": "text/html, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }

        try:
            response = await self._http.get(
                f"{self._base_url}/vacancies",
                params=params,
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Хабр Карьера: ошибка запроса — %s", exc)
            return []

        soup = BeautifulSoup(response.text, "lxml")
        vacancies: list[Vacancy] = []

        for card in soup.select("div.vacancy-card"):
            link_tag = card.select_one("a.vacancy-card__title-link")
            if not link_tag:
                continue

            title = link_tag.get_text(strip=True)
            href = link_tag.get("href", "")
            url = f"{self._base_url}{href}" if href.startswith("/") else str(href)

            # Извлекаем external_id из href: /vacancies/1234567890
            ext_id_match = re.search(r"/vacancies/(\d+)", str(href))
            external_id = ext_id_match.group(1) if ext_id_match else str(href)

            company_tag = card.select_one("a.vacancy-card__company-title")
            company = company_tag.get_text(strip=True) if company_tag else None

            salary_tag = card.select_one("div.vacancy-card__salary")
            salary = salary_tag.get_text(strip=True) if salary_tag else None

            desc_tag = card.select_one("div.vacancy-card__skills")
            description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

            vacancies.append(
                Vacancy(
                    external_id=external_id,
                    platform="habr",
                    title=title,
                    description=description,
                    schedule=WorkSchedule.REMOTE if remote_only else WorkSchedule.OFFICE,
                    url=url,
                    company=company,
                    salary=salary,
                )
            )

        logger.info("Хабр Карьера: найдено %d вакансий", len(vacancies))
        return vacancies

    async def apply_to_vacancy(
        self, vacancy_id: str, cover_letter: str
    ) -> ApplyResult:
        """Хабр Карьера не поддерживает авто-отклик через API."""
        return ApplyResult(
            ok=False,
            status_code=0,
            reason="Хабр Карьера: авто-отклик невозможен (нет API), откликнитесь вручную",
        )

    async def fetch_invitations(self) -> list[Invitation]:
        """Приглашения недоступны без авторизации."""
        return []


# ────────────────────────────────────────────────
#  Авито Работа (avito.ru)
# ────────────────────────────────────────────────


class AvitoJobClient:
    """Клиент Авито Работа — HTML-парсинг раздела вакансий.

    Поиск чужих вакансий через официальный API невозможен (API для продавцов/HR),
    поэтому парсим публичную страницу поисковой выдачи.
    """

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http = http_client
        self._base_url = "https://www.avito.ru"

    async def fetch_vacancies(
        self, search_query: str, remote_only: bool = True
    ) -> list[Vacancy]:
        # avito.ru/rossiya/vakansii?q=<query>
        params: dict[str, str] = {"q": search_query}
        url = f"{self._base_url}/rossiya/vakansii"

        headers = {
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9",
        }

        try:
            response = await self._http.get(
                url, params=params, headers=headers, follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Авито Работа: ошибка запроса — %s", exc)
            return []

        soup = BeautifulSoup(response.text, "lxml")
        vacancies: list[Vacancy] = []

        # Авито использует data-marker="item" на карточках
        for card in soup.select("[data-marker='item']"):
            title_tag = card.select_one("[itemprop='name']")
            if not title_tag:
                # Альтернативный селектор
                title_tag = card.select_one("h3")
            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)

            link_tag = card.select_one("a[itemprop='url']")
            if not link_tag:
                link_tag = card.select_one("a[href*='/vakansii/']")  # noqa: S106
            href = link_tag.get("href", "") if link_tag else ""
            item_url = f"{self._base_url}{href}" if href.startswith("/") else str(href)

            # external_id из URL: _1234567890
            ext_id_match = re.search(r"_(\d+)$", str(href))
            external_id = ext_id_match.group(1) if ext_id_match else str(href)

            price_tag = card.select_one("[itemprop='price']")
            if not price_tag:
                price_tag = card.select_one("[data-marker='item-price']")
            salary = price_tag.get_text(strip=True) if price_tag else None

            desc_tag = card.select_one("[class*='description']")
            description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

            vacancies.append(
                Vacancy(
                    external_id=external_id,
                    platform="avito",
                    title=title,
                    description=description,
                    schedule=WorkSchedule.REMOTE if remote_only else WorkSchedule.OFFICE,
                    url=item_url,
                    company=None,
                    salary=salary,
                )
            )

        logger.info("Авито Работа: найдено %d вакансий", len(vacancies))
        return vacancies

    async def apply_to_vacancy(
        self, vacancy_id: str, cover_letter: str
    ) -> ApplyResult:
        """Авито не поддерживает авто-отклик через API."""
        return ApplyResult(
            ok=False,
            status_code=0,
            reason="Авито Работа: авто-отклик невозможен, откликнитесь вручную",
        )

    async def fetch_invitations(self) -> list[Invitation]:
        return []


# ────────────────────────────────────────────────
#  Freelance.ru
# ────────────────────────────────────────────────


class FreelanceRuClient:
    """Клиент Freelance.ru — HTML-парсинг списка проектов.

    Публичного API нет; парсим страницу каталога проектов.
    """

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http = http_client
        self._base_url = "https://freelance.ru"

    async def fetch_vacancies(
        self, search_query: str, remote_only: bool = True
    ) -> list[Vacancy]:
        params: dict[str, str] = {"q": search_query}
        headers = {
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9",
        }

        try:
            response = await self._http.get(
                f"{self._base_url}/projects",
                params=params,
                headers=headers,
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Freelance.ru: ошибка запроса — %s", exc)
            return []

        soup = BeautifulSoup(response.text, "lxml")
        vacancies: list[Vacancy] = []

        # Freelance.ru: карточки проектов внутри div.project или article
        for card in soup.select("div.project, article.project, div[class*='project']"):
            title_tag: Tag | None = card.select_one(
                "a.project__title, h2 a, a[class*='title']"
            )
            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            href = title_tag.get("href", "")
            url = f"{self._base_url}{href}" if href.startswith("/") else str(href)

            ext_id_match = re.search(r"/(\d+)", str(href))
            external_id = ext_id_match.group(1) if ext_id_match else str(href)

            budget_tag = card.select_one(
                "span.project__budget, span[class*='price'], span[class*='budget']"
            )
            salary = budget_tag.get_text(strip=True) if budget_tag else None

            desc_tag = card.select_one(
                "div.project__description, p[class*='description'], div[class*='text']"
            )
            description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

            vacancies.append(
                Vacancy(
                    external_id=external_id,
                    platform="freelance_ru",
                    title=title,
                    description=description,
                    schedule=WorkSchedule.REMOTE,  # Фриланс — всегда удалёнка
                    url=url,
                    company=None,
                    salary=salary,
                )
            )

        logger.info("Freelance.ru: найдено %d проектов", len(vacancies))
        return vacancies

    async def apply_to_vacancy(
        self, vacancy_id: str, cover_letter: str
    ) -> ApplyResult:
        """Freelance.ru не поддерживает авто-отклик."""
        return ApplyResult(
            ok=False,
            status_code=0,
            reason="Freelance.ru: авто-отклик невозможен, откликнитесь вручную",
        )

    async def fetch_invitations(self) -> list[Invitation]:
        return []


# ────────────────────────────────────────────────
#  Workzilla (work-zilla.com)
# ────────────────────────────────────────────────


class WorkzillaClient:
    """Клиент Workzilla — HTML-парсинг ленты заданий.

    Публичного API нет; парсим публичную ленту заданий.
    Площадка активно борется с ботами, потому делаем паузу между запросами.
    """

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http = http_client
        self._base_url = "https://work-zilla.com"

    async def fetch_vacancies(
        self, search_query: str, remote_only: bool = True
    ) -> list[Vacancy]:
        await asyncio.sleep(2.0)  # Пауза для уменьшения нагрузки на сервер

        params: dict[str, str] = {"search": search_query}
        headers = {
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9",
        }

        try:
            response = await self._http.get(
                f"{self._base_url}/projects",
                params=params,
                headers=headers,
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Workzilla: ошибка запроса — %s", exc)
            return []

        soup = BeautifulSoup(response.text, "lxml")
        vacancies: list[Vacancy] = []

        # work-zilla.com: задания обёрнуты в div.task или аналогичный контейнер
        for card in soup.select(
            "div.task, div[class*='task-item'], div[class*='project'], article"
        ):
            title_tag: Tag | None = card.select_one(
                "a.task__title, h3 a, a[class*='title'], a[class*='name']"
            )
            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            href = title_tag.get("href", "")
            url = f"{self._base_url}{href}" if href.startswith("/") else str(href)

            ext_id_match = re.search(r"/(\d+)", str(href))
            external_id = ext_id_match.group(1) if ext_id_match else str(href)

            price_tag = card.select_one(
                "span.task__price, span[class*='price'], span[class*='budget']"
            )
            salary = price_tag.get_text(strip=True) if price_tag else None

            desc_tag = card.select_one(
                "div.task__description, p[class*='description'], div[class*='text']"
            )
            description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

            vacancies.append(
                Vacancy(
                    external_id=external_id,
                    platform="workzilla",
                    title=title,
                    description=description,
                    schedule=WorkSchedule.REMOTE,  # Фриланс — всегда удалёнка
                    url=url,
                    company=None,
                    salary=salary,
                )
            )

        logger.info("Workzilla: найдено %d заданий", len(vacancies))
        return vacancies

    async def apply_to_vacancy(
        self, vacancy_id: str, cover_letter: str
    ) -> ApplyResult:
        """Workzilla не поддерживает авто-отклик."""
        return ApplyResult(
            ok=False,
            status_code=0,
            reason="Workzilla: авто-отклик невозможен, откликнитесь вручную",
        )

    async def fetch_invitations(self) -> list[Invitation]:
        return []
