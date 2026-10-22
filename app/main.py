import asyncio
import logging

import httpx
from aiogram import Bot

from app.adapters.platforms import HeadHunterClient, SuperJobClient
from app.adapters.scrapers import (
    AvitoJobClient,
    FreelanceRuClient,
    HabrCareerClient,
    WorkzillaClient,
)
from app.adapters.telegram_notifier import AiogramNotificationSender
from app.config import Settings
from app.core.job_hunter import JobHunterService, JobPlatformClient, VacancyFilterCriteria
from app.db.models import ProcessedItemRepository
from app.db.session import create_session_factory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_polling_cycle(
    service: JobHunterService,
    repo: ProcessedItemRepository,
    platform_name: str,
    search_query: str,
) -> None:
    """Один цикл: откликнуться на новые вакансии и проверить ответы."""
    if not search_query or not search_query.strip():
        logger.warning(
            "Поисковый запрос пуст. Пропуск цикла поиска для платформы %s",
            platform_name,
        )
        return

    applied_ids = await repo.get_processed_ids(platform_name, "vacancy")
    new_applied = await service.search_and_apply(search_query.strip(), applied_ids)
    await repo.mark_as_processed(platform_name, "vacancy", new_applied)
    logger.info(
        "Платформа %s: отправлено новых откликов: %d",
        platform_name,
        len(new_applied),
    )

    notified_ids = await repo.get_processed_ids(platform_name, "invitation")
    new_invites = await service.process_invitations(notified_ids)
    invite_ids = [inv.external_id for inv in new_invites]
    await repo.mark_as_processed(platform_name, "invitation", invite_ids)
    logger.info(
        "Платформа %s: обработано новых приглашений: %d",
        platform_name,
        len(invite_ids),
    )


def _build_clients(
    settings: Settings,
    http_client: httpx.AsyncClient,
) -> dict[str, JobPlatformClient]:
    """Собирает словарь активных клиентов площадок на основе конфигурации."""
    clients: dict[str, JobPlatformClient] = {}

    # hh.ru
    if settings.enable_hh:
        clients["hh"] = HeadHunterClient(
            http_client=http_client,
            access_token=settings.hh_access_token.get_secret_value(),
            resume_id=settings.hh_resume_id,
            base_url="https://api.hh.ru",
            platform_name="hh",
        )

    # zarplata.ru (единое API с hh.ru)
    if settings.enable_zarplata:
        clients["zarplata"] = HeadHunterClient(
            http_client=http_client,
            access_token=settings.hh_access_token.get_secret_value(),
            resume_id=settings.hh_resume_id,
            base_url="https://api.zarplata.ru",
            platform_name="zarplata",
        )

    # SuperJob (API)
    if settings.enable_superjob:
        if settings.superjob_configured:
            assert settings.superjob_secret_key is not None  # noqa: S101
            assert settings.superjob_access_token is not None  # noqa: S101
            assert settings.superjob_resume_id is not None  # noqa: S101
            clients["superjob"] = SuperJobClient(
                http_client=http_client,
                secret_key=settings.superjob_secret_key.get_secret_value(),
                access_token=settings.superjob_access_token.get_secret_value(),
                resume_id=settings.superjob_resume_id,
            )
        else:
            logger.warning(
                "SuperJob включён (ENABLE_SUPERJOB=true), но не хватает "
                "SUPERJOB_SECRET_KEY / SUPERJOB_ACCESS_TOKEN / SUPERJOB_RESUME_ID. "
                "Площадка пропущена."
            )

    # Хабр Карьера (scraping)
    if settings.enable_habr:
        clients["habr"] = HabrCareerClient(http_client=http_client)

    # Авито Работа (scraping)
    if settings.enable_avito:
        clients["avito"] = AvitoJobClient(http_client=http_client)

    # Freelance.ru (scraping)
    if settings.enable_freelance_ru:
        clients["freelance_ru"] = FreelanceRuClient(http_client=http_client)

    # Workzilla (scraping)
    if settings.enable_workzilla:
        clients["workzilla"] = WorkzillaClient(http_client=http_client)

    return clients


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    engine, session_factory = create_session_factory(
        settings.database_url.get_secret_value()
    )

    bot = Bot(token=settings.bot_token.get_secret_value())
    notifier = AiogramNotificationSender(bot=bot, chat_id=settings.telegram_chat_id)
    criteria = VacancyFilterCriteria(remote_only=True)

    async with httpx.AsyncClient(timeout=30.0) as http_client:
        clients = _build_clients(settings, http_client)

        if not clients:
            logger.error(
                "Ни одна площадка не включена! "
                "Проверьте переменные ENABLE_* в .env"
            )
            return

        enabled_names = ", ".join(clients)
        logger.info("Активные площадки: %s", enabled_names)

        try:
            while True:
                for platform_name, client in clients.items():
                    try:
                        async with session_factory() as session:
                            repo = ProcessedItemRepository(session)
                            service = JobHunterService(
                                platform_client=client,
                                notifier=notifier,
                                criteria=criteria,
                                cover_letter=settings.default_cover_letter,
                            )
                            await run_polling_cycle(
                                service=service,
                                repo=repo,
                                platform_name=platform_name,
                                search_query=settings.search_query,
                            )
                    except Exception:
                        logger.exception("Ошибка при опросе площадки %s", platform_name)

                await asyncio.sleep(settings.poll_interval_seconds)
        finally:
            await bot.session.close()
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
