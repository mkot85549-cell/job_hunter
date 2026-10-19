import asyncio

import httpx

from app.core.job_hunter import Invitation, Vacancy, WorkSchedule


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

    async def fetch_vacancies(self, search_query: str) -> list[Vacancy]:
        params = {
            "text": search_query,
            "schedule": "remote",
            "per_page": 50,
        }
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
            vacancies.append(
                Vacancy(
                    external_id=str(item["id"]),
                    platform=self._platform,
                    title=item["name"],
                    description=description,
                    schedule=WorkSchedule.REMOTE,
                    url=item.get("alternate_url", ""),
                )
            )
        return vacancies

    async def apply_to_vacancy(self, vacancy_id: str, cover_letter: str) -> bool:
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
        return response.status_code in (201, 204)

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

    async def fetch_vacancies(self, search_query: str) -> list[Vacancy]:
        params = {
            "keyword": search_query,
            "place_of_work": 2,  # 2 = Удаленная работа (на дому) в API SuperJob
            "count": 50,
        }
        response = await self._http.get(
            f"{self._base_url}/vacancies/",
            params=params,
            headers=self._headers,
        )
        response.raise_for_status()
        objects = response.json().get("objects", [])

        return [
            Vacancy(
                external_id=str(obj["id"]),
                platform="superjob",
                title=obj.get("profession", ""),
                description=obj.get("candidat", ""),
                schedule=WorkSchedule.REMOTE,
                url=obj.get("link", ""),
            )
            for obj in objects
        ]

    async def apply_to_vacancy(self, vacancy_id: str, cover_letter: str) -> bool:
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
        return response.status_code == 200

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
