"""Async HTTP-клиент: лимит скорости, ограничение параллельности, ретраи, ротация UA."""

from __future__ import annotations

import asyncio
import logging
import random
import time

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from pipeline.config import Settings

log = logging.getLogger(__name__)

RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}


class RetryableStatus(Exception):
    def __init__(self, status: int, url: str):
        super().__init__(f"HTTP {status} for {url}")
        self.status = status


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, RetryableStatus | httpx.TransportError | httpx.TimeoutException)


class RateLimiter:
    """Простой интервальный лимитер: не чаще N запросов в секунду на весь клиент."""

    def __init__(self, rps: float):
        self._interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        if not self._interval:
            return
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            if delay > 0:
                await asyncio.sleep(delay)
                now = time.monotonic()
            self._next = now + self._interval


class Fetcher:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.s = settings
        self._sem = asyncio.Semaphore(settings.concurrency)
        self._limiter = RateLimiter(settings.requests_per_second)
        self._client = httpx.AsyncClient(
            timeout=settings.timeout_s,
            follow_redirects=True,
            proxy=settings.proxy,
            transport=transport,
            headers={"Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"},
        )
        self.stats = {"requests": 0, "retries": 0, "failed": 0}

    async def __aenter__(self) -> Fetcher:
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def get_text(self, url: str, **params) -> str:
        """Вернуть HTML/текст страницы или поднять исключение после всех ретраев."""
        async with self._sem:
            try:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(self.s.max_retries),
                    wait=wait_exponential(
                        multiplier=self.s.retry_wait_initial_s, max=self.s.retry_wait_max_s
                    )
                    + wait_random(0, self.s.retry_wait_initial_s),
                    retry=retry_if_exception(_is_retryable),
                    reraise=True,
                ):
                    with attempt:
                        if attempt.retry_state.attempt_number > 1:
                            self.stats["retries"] += 1
                            log.warning("retry %s: %s", attempt.retry_state.attempt_number, url)
                        await self._limiter.wait()
                        self.stats["requests"] += 1
                        resp = await self._client.get(
                            url,
                            params=params or None,
                            headers={"User-Agent": random.choice(self.s.user_agents)},
                        )
                        if resp.status_code in RETRY_STATUSES:
                            raise RetryableStatus(resp.status_code, url)
                        resp.raise_for_status()
                        return resp.text
            except Exception as e:
                # 404 на пагинации - нормальный конец списка, не ошибка
                if not (isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 404):
                    self.stats["failed"] += 1
                raise
        raise RuntimeError("unreachable")
