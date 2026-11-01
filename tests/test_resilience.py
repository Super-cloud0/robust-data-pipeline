from __future__ import annotations

import httpx

from pipeline.http import Fetcher
from pipeline.sources.books_demo import BooksDemoScraper


async def test_stops_when_source_is_down(settings):
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    async with Fetcher(settings, transport=httpx.MockTransport(handler)) as f:
        result = await BooksDemoScraper(f).run()

    assert result.records == []
    assert len(result.rejected) == BooksDemoScraper.max_list_failures
    # 3 страницы x 3 попытки, а не 50 страниц
    assert calls["n"] == BooksDemoScraper.max_list_failures * settings.max_retries
