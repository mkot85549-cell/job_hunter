import asyncio
import logging

import httpx
from aiogram import Bot

from app.adapters.platforms import HeadHunterClient
from app.adapters.telegram_notifier import AiogramNotificationSender
from app.config import Settings
from app.core.job_hunter import JobHunterService, VacancyFilterCriteria
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
    applied_ids = await repo.get_processed_ids(platform_name, "vacancy")
    new_applied = await service.search_and_apply(search_query, applied_ids)
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


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    engine, session_factory = create_session_factory(
        settings.database_url.get_secret_value()
    )

    bot = Bot(token=settings.bot_token.get_secret_value())
    notifier = AiogramNotificationSender(bot=bot, chat_id=settings.telegram_chat_id)
    criteria = VacancyFilterCriteria(remote_only=True)

    async with httpx.AsyncClient(timeout=20.0) as http_client:
        # Клиенты для HH и Zarplata (единый движок API)
        clients = {
            "hh": HeadHunterClient(
                http_client=http_client,
                access_token=settings.hh_access_token.get_secret_value(),
                resume_id=settings.hh_resume_id,
                base_url="https://api.hh.ru",
                platform_name="hh",
            ),
            "zarplata": HeadHunterClient(
                http_client=http_client,
                access_token=settings.hh_access_token.get_secret_value(),
                resume_id=settings.hh_resume_id,
                base_url="https://api.zarplata.ru",
                platform_name="zarplata",
            ),
        }

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
