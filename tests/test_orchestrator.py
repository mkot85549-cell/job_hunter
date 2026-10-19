"""Тесты оркестратора: retry_async + MultiPlatformOrchestrator."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.core.orchestrator import MultiPlatformOrchestrator, PlatformSyncResult, retry_async


# ────────────────────────────────────────────────
#  PlatformSyncResult
# ────────────────────────────────────────────────


class TestPlatformSyncResult:
    """Тесты дата-класса результата синхронизации."""

    def test_is_success_when_no_error(self) -> None:
        result = PlatformSyncResult(
            platform_name="hh", applied_count=5, invitations_count=1
        )
        assert result.is_success is True

    def test_is_not_success_when_error(self) -> None:
        result = PlatformSyncResult(
            platform_name="hh",
            applied_count=0,
            invitations_count=0,
            error="Connection refused",
        )
        assert result.is_success is False

    def test_frozen_dataclass(self) -> None:
        result = PlatformSyncResult(
            platform_name="hh", applied_count=0, invitations_count=0
        )
        with pytest.raises(AttributeError):
            result.applied_count = 99  # type: ignore[misc]


# ────────────────────────────────────────────────
#  retry_async
# ────────────────────────────────────────────────


class TestRetryAsync:
    """Тесты функции retry с экспоненциальным откатом."""

    pytestmark = pytest.mark.asyncio(loop_scope="function")

    async def test_succeeds_on_first_attempt(self) -> None:
        async def ok() -> str:
            return "ok"

        result = await retry_async(ok, max_attempts=3, base_delay=0.01)
        assert result == "ok"

    async def test_recovers_from_rate_limit(self) -> None:
        """При 429 Too Many Requests функция делает повтор и побеждает."""
        attempts = 0

        async def flaky_endpoint() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                req = httpx.Request("GET", "https://api.example.com")
                resp = httpx.Response(429, request=req)
                raise httpx.HTTPStatusError("Rate limit", request=req, response=resp)
            return "ok"

        result = await retry_async(flaky_endpoint, max_attempts=3, base_delay=0.01)
        assert result == "ok"
        assert attempts == 3

    async def test_raises_immediately_on_client_4xx(self) -> None:
        """Клиентские ошибки 400/401/403/404 не ретраятся, пробрасываются сразу."""
        for status_code in (400, 401, 403, 404):
            attempts = 0

            async def fail_with_client_error() -> str:
                nonlocal attempts
                attempts += 1
                req = httpx.Request("GET", "https://api.example.com")
                resp = httpx.Response(status_code, request=req)
                raise httpx.HTTPStatusError("Client error", request=req, response=resp)

            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await retry_async(fail_with_client_error, max_attempts=3, base_delay=0.01)
            assert exc_info.value.response.status_code == status_code
            assert attempts == 1  # Только одна попытка, без ретрая

    async def test_retries_on_500_then_raises(self) -> None:
        """Серверные 5xx ретраятся, но если все попытки исчерпаны — бросается последнее исключение."""
        attempts = 0

        async def always_500() -> str:
            nonlocal attempts
            attempts += 1
            req = httpx.Request("GET", "https://api.example.com")
            resp = httpx.Response(500, request=req)
            raise httpx.HTTPStatusError("Server error", request=req, response=resp)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await retry_async(always_500, max_attempts=3, base_delay=0.01)
        assert exc_info.value.response.status_code == 500
        assert attempts == 3

    async def test_retries_on_request_error(self) -> None:
        """Сетевые ошибки (таймаут, DNS) тоже ретраятся."""
        attempts = 0

        async def network_fail() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise httpx.ConnectError("Connection refused")
            return "recovered"

        result = await retry_async(network_fail, max_attempts=3, base_delay=0.01)
        assert result == "recovered"
        assert attempts == 2

    async def test_exhausted_network_errors_raises_last(self) -> None:
        """Если все попытки провалились из-за сетевой ошибки — бросается последняя."""
        async def always_timeout() -> str:
            raise httpx.ReadTimeout("Timeout")

        with pytest.raises(httpx.ReadTimeout):
            await retry_async(always_timeout, max_attempts=2, base_delay=0.01)

    async def test_single_attempt_no_retry(self) -> None:
        """max_attempts=1 — одна попытка без ретрая."""
        attempts = 0

        async def fail_once() -> str:
            nonlocal attempts
            attempts += 1
            raise httpx.ConnectError("fail")

        with pytest.raises(httpx.ConnectError):
            await retry_async(fail_once, max_attempts=1, base_delay=0.01)
        assert attempts == 1


# ────────────────────────────────────────────────
#  MultiPlatformOrchestrator
# ────────────────────────────────────────────────


class TestMultiPlatformOrchestrator:
    """Тесты конкурентного оркестратора площадок."""

    pytestmark = pytest.mark.asyncio(loop_scope="function")

    async def test_runs_platforms_concurrently(self) -> None:
        """3 площадки по 0.1 сек выполняются за ~0.1 сек, а не за 0.3 сек."""
        orchestrator = MultiPlatformOrchestrator(max_concurrent_platforms=3)

        async def simulated_io_worker() -> tuple[int, int]:
            await asyncio.sleep(0.1)
            return (5, 1)

        tasks_map = {
            "hh": simulated_io_worker,
            "superjob": simulated_io_worker,
            "avito": simulated_io_worker,
        }

        start_time = time.perf_counter()
        results = await orchestrator.sync_all(tasks_map)
        elapsed = time.perf_counter() - start_time

        assert len(results) == 3
        assert all(r.is_success for r in results)
        assert elapsed < 0.22

    async def test_isolates_failing_platform(self) -> None:
        """Падение одного API (403 Error) не отменяет работу остальных."""
        orchestrator = MultiPlatformOrchestrator(max_concurrent_platforms=3)

        async def healthy_worker() -> tuple[int, int]:
            await asyncio.sleep(0.02)
            return (10, 2)

        async def broken_worker() -> tuple[int, int]:
            request = httpx.Request("GET", "https://api.example.com")
            response = httpx.Response(403, request=request)
            raise httpx.HTTPStatusError("Forbidden", request=request, response=response)

        tasks_map = {
            "hh": healthy_worker,
            "broken_api": broken_worker,
            "superjob": healthy_worker,
        }

        results = await orchestrator.sync_all(tasks_map)
        results_by_name = {r.platform_name: r for r in results}

        assert results_by_name["hh"].is_success is True
        assert results_by_name["hh"].applied_count == 10

        assert results_by_name["superjob"].is_success is True

        assert results_by_name["broken_api"].is_success is False
        assert results_by_name["broken_api"].error is not None

    async def test_semaphore_limits_concurrency(self) -> None:
        """С семафором=2 и 4 задачами — максимум 2 работают одновременно."""
        orchestrator = MultiPlatformOrchestrator(max_concurrent_platforms=2)
        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def tracked_worker() -> tuple[int, int]:
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
            await asyncio.sleep(0.05)
            async with lock:
                current_concurrent -= 1
            return (1, 0)

        tasks_map = {
            f"platform_{i}": tracked_worker for i in range(4)
        }

        results = await orchestrator.sync_all(tasks_map)
        assert len(results) == 4
        assert all(r.is_success for r in results)
        assert max_concurrent <= 2

    async def test_empty_tasks_map(self) -> None:
        orchestrator = MultiPlatformOrchestrator()
        results = await orchestrator.sync_all({})
        assert results == []

    async def test_single_platform(self) -> None:
        orchestrator = MultiPlatformOrchestrator()

        async def worker() -> tuple[int, int]:
            return (42, 7)

        results = await orchestrator.sync_all({"only": worker})
        assert len(results) == 1
        assert results[0].platform_name == "only"
        assert results[0].applied_count == 42
        assert results[0].invitations_count == 7

    async def test_runtime_error_is_captured(self) -> None:
        """Не-httpx исключение (RuntimeError) тоже ловится и не роняет остальных."""
        orchestrator = MultiPlatformOrchestrator(max_concurrent_platforms=3)

        async def crash() -> tuple[int, int]:
            msg = "unexpected crash"
            raise RuntimeError(msg)

        async def ok() -> tuple[int, int]:
            return (1, 1)

        results = await orchestrator.sync_all({"crash": crash, "ok": ok})
        by_name = {r.platform_name: r for r in results}

        assert by_name["crash"].is_success is False
        assert "unexpected crash" in (by_name["crash"].error or "")
        assert by_name["ok"].is_success is True