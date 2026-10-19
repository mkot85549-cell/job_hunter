import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(slots=True, frozen=True)
class PlatformSyncResult:
    platform_name: str
    applied_count: int
    invitations_count: int
    error: str | None = None

    @property
    def is_success(self) -> bool:
        return self.error is None


async def retry_async[T](
    func: Callable[[], Awaitable[T]],
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> T:
    """Выполняет корутину с экспоненциальной задержкой и джиттером при сбоях сети."""
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await func()
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            # Не ретраим клиентские ошибки (400, 401, 403, 404), кроме 429 (Rate Limit)
            if isinstance(exc, httpx.HTTPStatusError):
                status = exc.response.status_code
                if status < 500 and status != 429:
                    raise

            if attempt == max_attempts:
                break

            # Экспоненциальный рост паузы + случайный разброс (jitter) от 0 до 0.5 сек
            delay = (base_delay * (2 ** (attempt - 1))) + random.uniform(0.0, 0.5)  # noqa: S311
            logger.warning(
                "Сбой запроса (%s). Попытка %d/%d через %.2f сек...",
                exc,
                attempt,
                max_attempts,
                delay,
            )
            await asyncio.sleep(delay)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Unreachable retry state")


class MultiPlatformOrchestrator:
    """Координирует одновременный опрос нескольких API с ограничением параллелизма."""

    def __init__(self, max_concurrent_platforms: int = 3) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent_platforms)

    async def _run_single_platform(
        self,
        platform_name: str,
        worker_coro: Callable[[], Awaitable[tuple[int, int]]],
    ) -> PlatformSyncResult:
        """Безопасная обертка (Bulkhead): ловит ошибки конкретной площадки."""
        async with self._semaphore:
            try:
                applied_cnt, invites_cnt = await retry_async(worker_coro)
                return PlatformSyncResult(
                    platform_name=platform_name,
                    applied_count=applied_cnt,
                    invitations_count=invites_cnt,
                )
            except Exception as exc:
                logger.exception("Площадка %s завершилась с ошибкой", platform_name)
                return PlatformSyncResult(
                    platform_name=platform_name,
                    applied_count=0,
                    invitations_count=0,
                    error=str(exc),
                )

    async def sync_all(
        self,
        tasks_map: dict[str, Callable[[], Awaitable[tuple[int, int]]]],
    ) -> list[PlatformSyncResult]:
        """Запускает обработку всех площадок конкурентно через TaskGroup."""
        running_tasks: list[asyncio.Task[PlatformSyncResult]] = []

        async with asyncio.TaskGroup() as tg:
            for platform_name, worker_coro in tasks_map.items():
                task = tg.create_task(
                    self._run_single_platform(platform_name, worker_coro),
                    name=f"sync_{platform_name}",
                )
                running_tasks.append(task)

        return [task.result() for task in running_tasks]
