from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.job_hunter import ApplyResult, Invitation, Vacancy, WorkSchedule


def _format_salary(salary_dict: dict[str, Any] | None) -> str | None:
    """Форматирует вилку зарплаты в человекочитаемую строку."""
    if not salary_dict:
        return None
    s_from = salary_dict.get("from")
    s_to = salary_dict.get("to")
    currency = salary_dict.get("currency") or "RUR"
    currency_symbol = {
        "RUR": "₽",
        "RUB": "₽",
        "USD": "$",
        "EUR": "€",
        "KZT": "₸",
        "BYR": "Br",
        "BYN": "Br",
    }.get(currency, currency)

    def _fmt(n: int | float) -> str:
        return f"{int(n):,}".replace(",", " ")

    if s_from is not None and s_to is not None:
        return f"{_fmt(s_from)} – {_fmt(s_to)} {currency_symbol}"
    if s_from is not None:
        return f"от {_fmt(s_from)} {currency_symbol}"
    if s_to is not None:
        return f"до {_fmt(s_to)} {currency_symbol}"
    return None


class HeadHunterClient:
    """Подходит для hh.ru и zarplata.ru (единое API)."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        access_token: str,
        resume_id: str,
        base_url: str = "https://api.hh.ru",
        platform_name: str = "hh",
    ) -> None:
        self._http = http_client
        self._resume_id = resume_id
        self._base_url = base_url
        self._platform = platform_name
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "HH-User-Agent": "JobHunterBot/1.0 (contact@example.com)",
        }

    async def fetch_vacancies(
        self, search_query: str, remote_only: bool = True
    ) -> list[Vacancy]:
        params: dict[str, Any] = {
            "text": search_query,
            "per_page": 50,
        }
        if remote_only:
            # schedule=remote поддерживается как hh.ru, так и zarplata.ru;
            # work_format=REMOTE используется в новейших спецификациях dev.hh.ru
            params["schedule"] = "remote"
            params["work_format"] = "REMOTE"

        response = await self._http.get(
            f"{self._base_url}/vacancies",
            params=params,
            headers=self._headers,
        )
        response.raise_for_status()
        data = response.json()

        vacancies: list[Vacancy] = []
        for item in data.get("items", []):
            snippet = item.get("snippet") or {}
            req = snippet.get("requirement", "") or ""
            resp = snippet.get("responsibility", "") or ""
            description = f"{req} {resp}".strip()
            employer = item.get("employer") or {}
            company = employer.get("name")
            salary = _format_salary(item.get("salary"))

            vacancies.append(
                Vacancy(
                    external_id=str(item["id"]),
                    platform=self._platform,
                    title=item["name"],
                    description=description,
                    schedule=WorkSchedule.REMOTE,
                    url=item.get("alternate_url", ""),
                    company=company,
                    salary=salary,
                )
            )
        return vacancies

    async def apply_to_vacancy(
        self, vacancy_id: str, cover_letter: str
    ) -> ApplyResult:
        await asyncio.sleep(1.5)  # Защита от Rate Limit
        payload = {
            "vacancy_id": vacancy_id,
            "resume_id": self._resume_id,
            "message": cover_letter,
        }
        response = await self._http.post(
            f"{self._base_url}/negotiations",
            data=payload,
            headers=self._headers,
        )
        if response.status_code in (201, 204):
            return ApplyResult(ok=True, status_code=response.status_code)

        reason: str | None = None
        if response.status_code == 403:
            try:
                err_data = response.json()
                errors = err_data.get("errors", [])
                types = [
                    e.get("type", "").lower()
                    for e in errors
                    if isinstance(e, dict)
                ]
                if any("test" in t for t in types):
                    reason = "Требуется прохождение теста"
                elif any("message" in t or "letter" in t for t in types):
                    reason = "Требуется обязательное сопроводительное письмо"
                else:
                    reason = (
                        err_data.get("description")
                        or (errors[0].get("value") if errors else None)
                        or "Требуется тест или сопроводительное письмо (403)"
                    )
            except Exception:
                reason = "Требуется тест или сопроводительное письмо (403)"
        elif response.status_code == 409:
            reason = "Уже откликнулись ранее (409)"
        else:
            reason = f"Ошибка отклика: HTTP {response.status_code}"

        return ApplyResult(
            ok=False,
            status_code=response.status_code,
            reason=reason,
        )

    async def fetch_invitations(self) -> list[Invitation]:
        response = await self._http.get(
            f"{self._base_url}/negotiations",
            params={"status": "invitation"},
            headers=self._headers,
        )
        response.raise_for_status()
        items = response.json().get("items", [])

        invitations: list[Invitation] = []
        for item in items:
            neg_id = str(item["id"])
            vacancy = item.get("vacancy") or {}
            messages_resp = await self._http.get(
                f"{self._base_url}/negotiations/{neg_id}/messages",
                headers=self._headers,
            )
            if messages_resp.status_code != 200:
                continue

            messages = messages_resp.json().get("items", [])
            full_text = "\n".join(m.get("text", "") for m in messages if m.get("text"))
            invitations.append(
                Invitation(
                    external_id=neg_id,
                    vacancy_title=vacancy.get("name", "Без названия"),
                    vacancy_url=vacancy.get("alternate_url", ""),
                    message_text=full_text,
                )
            )
        return invitations


class SuperJobClient:
    """Клиент для SuperJob API (api.superjob.ru)."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        secret_key: str,
        access_token: str,
        resume_id: int,
    ) -> None:
        self._http = http_client
        self._resume_id = resume_id
        self._base_url = "https://api.superjob.ru/2.0"
        self._headers = {
            "X-Api-App-Id": secret_key,
            "Authorization": f"Bearer {access_token}",
        }

    async def fetch_vacancies(
        self, search_query: str, remote_only: bool = True
    ) -> list[Vacancy]:
        params: dict[str, Any] = {
            "keyword": search_query,
            "count": 50,
        }
        if remote_only:
            params["place_of_work"] = 2  # 2 = Удаленная работа в SuperJob API
        response = await self._http.get(
            f"{self._base_url}/vacancies/",
            params=params,
            headers=self._headers,
        )
        response.raise_for_status()
        objects = response.json().get("objects", [])

        vacancies: list[Vacancy] = []
        for obj in objects:
            client_info = obj.get("client") or {}
            company = client_info.get("title") or obj.get("firm_name")
            p_from = obj.get("payment_from")
            p_to = obj.get("payment_to")
            salary = None
            if p_from and p_to:
                salary = f"{p_from:,} – {p_to:,} руб.".replace(",", " ")
            elif p_from:
                salary = f"от {p_from:,} руб.".replace(",", " ")
            elif p_to:
                salary = f"до {p_to:,} руб.".replace(",", " ")

            vacancies.append(
                Vacancy(
                    external_id=str(obj["id"]),
                    platform="superjob",
                    title=obj.get("profession", ""),
                    description=obj.get("candidat", ""),
                    schedule=WorkSchedule.REMOTE,
                    url=obj.get("link", ""),
                    company=company,
                    salary=salary,
                )
            )
        return vacancies

    async def apply_to_vacancy(
        self, vacancy_id: str, cover_letter: str
    ) -> ApplyResult:
        await asyncio.sleep(1.5)
        payload = {
            "id_vacancy": int(vacancy_id),
            "id_cv": self._resume_id,
            "comment": cover_letter,
        }
        response = await self._http.post(
            f"{self._base_url}/send_cv_on_vacancy/",
            json=payload,
            headers=self._headers,
        )
        is_ok = response.status_code == 200
        reason = None if is_ok else f"HTTP {response.status_code}"
        return ApplyResult(
            ok=is_ok,
            status_code=response.status_code,
            reason=reason,
        )

    async def fetch_invitations(self) -> list[Invitation]:
        response = await self._http.get(
            f"{self._base_url}/messages/",
            headers=self._headers,
        )
        response.raise_for_status()
        objects = response.json().get("objects", [])

        return [
            Invitation(
                external_id=str(obj["id"]),
                vacancy_title=obj.get("profession", "Вакансия SuperJob"),
                vacancy_url=obj.get("link", ""),
                message_text=obj.get("text", ""),
            )
            for obj in objects
        ]
