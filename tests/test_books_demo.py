from __future__ import annotations

from decimal import Decimal

from conftest import books_transport, fixture

from pipeline.http import Fetcher
from pipeline.sources.books_demo import BooksDemoScraper

URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"


def test_parse_list_resolves_absolute_urls(settings):
    s = BooksDemoScraper(Fetcher(settings))
    links = s.parse_list(
        fixture("books_list.html"), "https://books.toscrape.com/catalogue/page-1.html"
    )
    assert links[0] == URL
    assert len(links) == 2


def test_parse_item_fields(settings):
    raw = BooksDemoScraper(Fetcher(settings)).parse_item(fixture("books_item.html"), URL)
    rec = BooksDemoScraper.record_model(**raw)
    assert rec.title == "A Light in the Attic"
    assert rec.price == Decimal("51.77")
    assert rec.in_stock == 22
    assert rec.rating == 3
    assert rec.category == "Poetry"
    assert rec.upc == "a897fe39b1053632"


async def test_run_separates_valid_and_rejected(settings):
    transport, _ = books_transport()
    async with Fetcher(settings, transport=transport) as f:
        result = await BooksDemoScraper(f).run()
    assert len(result.records) == 1
    assert len(result.rejected) == 1
    assert result.rejected[0].reason.startswith("invalid:")
    assert "title" in result.rejected[0].reason


async def test_retries_on_503(settings):
    transport, calls = books_transport(fail_first=2)
    async with Fetcher(settings, transport=transport) as f:
        result = await BooksDemoScraper(f).run()
        assert f.stats["retries"] >= 2
    assert calls["item"] == 3
    assert len(result.records) == 1


async def test_limit(settings):
    transport, _ = books_transport()
    async with Fetcher(settings, transport=transport) as f:
        result = await BooksDemoScraper(f).run(limit=1)
    assert len(result.records) + len(result.rejected) == 1
