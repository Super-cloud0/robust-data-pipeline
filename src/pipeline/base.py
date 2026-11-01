"""Базовый скрапер. Новый источник = подкласс с тремя методами."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx
from pydantic import ValidationError

from pipeline.http import Fetcher
from pipeline.models import Record

log = logging.getLogger(__name__)


@dataclass
class Rejected:
    url: str
    reason: str
    raw: dict[str, Any] | None = None


@dataclass
class RunResult:
    records: list[Record] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)


class BaseScraper(ABC):
    """Схема работы: страницы списка -> ссылки на карточки -> парсинг карточки -> валидация.

    Если у источника всё есть прямо в списке (без карточек), переопределите `run`
    или верните из `item_urls` сами страницы списка.
    """

    name: ClassVar[str]
    record_model: ClassVar[type[Record]]
    max_list_failures: ClassVar[int] = 3  # подряд упавших страниц списка -> источник лежит

    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher

    @abstractmethod
    def list_urls(self) -> AsyncIterator[str]:
        """Страницы каталога/выдачи (пагинация)."""

    @abstractmethod
    def parse_list(self, html: str, page_url: str) -> list[str]:
        """Из страницы каталога достать ссылки на карточки."""

    @abstractmethod
    def parse_item(self, html: str, url: str) -> dict[str, Any]:
        """Из карточки достать сырые поля. Валидация - не здесь, а в модели."""

    async def run(self, limit: int | None = None) -> RunResult:
        result = RunResult()
        item_urls: list[str] = []
        seen: set[str] = set()

        failures_in_row = 0
        async for page_url in self.list_urls():
            try:
                html = await self.fetcher.get_text(page_url)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    break  # страницы кончились - это не ошибка
                reason = f"list fetch failed: HTTP {e.response.status_code}"
            except Exception as e:  # noqa: BLE001 - фиксируем и идём дальше
                reason = f"list fetch failed: {type(e).__name__}"
            else:
                reason = None
            if reason:
                result.rejected.append(Rejected(page_url, reason))
                failures_in_row += 1
                if failures_in_row >= self.max_list_failures:
                    log.error(
                        "%s: %d страниц списка подряд не загрузились, стоп",
                        self.name,
                        failures_in_row,
                    )
                    break
                continue
            failures_in_row = 0
            links = self.parse_list(html, page_url)
            if not links:
                break  # пустая страница = конец пагинации
            for u in links:
                if u not in seen:
                    seen.add(u)
                    item_urls.append(u)
            if limit and len(item_urls) >= limit:
                item_urls = item_urls[:limit]
                break

        log.info("%s: %d карточек к сбору", self.name, len(item_urls))
        await asyncio.gather(*(self._process(u, result) for u in item_urls))
        return result

    async def _process(self, url: str, result: RunResult) -> None:
        try:
            html = await self.fetcher.get_text(url)
        except Exception as e:  # noqa: BLE001
            result.rejected.append(Rejected(url, f"fetch failed: {e}"))
            return
        try:
            raw = self.parse_item(html, url)
        except Exception as e:  # noqa: BLE001 - сломанная вёрстка не роняет весь прогон
            result.rejected.append(Rejected(url, f"parse failed: {e}"))
            return
        try:
            result.records.append(self.record_model(**raw))
        except ValidationError as e:
            reason = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
            result.rejected.append(Rejected(url, f"invalid: {reason}", raw))
