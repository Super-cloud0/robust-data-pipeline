"""books.toscrape.com - песочница для парсинга. Образец для новых источников."""

from __future__ import annotations

import itertools
import os
import re
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from urllib.parse import urljoin

from pydantic import Field, HttpUrl, field_validator
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from pipeline.base import BaseScraper
from pipeline.models import Record

BASE = os.getenv("BOOKS_BASE_URL", "https://books.toscrape.com/")
RATING = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


class Book(Record):
    title: str = Field(min_length=1)
    price: Decimal = Field(ge=0)
    currency: str = "GBP"
    in_stock: int = Field(ge=0)
    rating: int = Field(ge=1, le=5)
    category: str | None = None
    upc: str | None = None
    url: HttpUrl

    @field_validator("price", mode="before")
    @classmethod
    def _price(cls, v: Any) -> Any:
        # "£51.77" / "51,77 ₸" / "1 299 ₽" -> Decimal
        if isinstance(v, str):
            cleaned = re.sub(r"[^\d,.]", "", v).replace(",", ".")
            return cleaned or None
        return v


def _text(tree: HTMLParser, css: str) -> str | None:
    node = tree.css_first(css)
    return node.text(strip=True) if node else None


class BooksDemoScraper(BaseScraper):
    name = "books_demo"
    record_model = Book

    async def list_urls(self) -> AsyncIterator[str]:
        # идём до первого 404 - так не нужно знать число страниц заранее
        for page in itertools.count(1):
            yield urljoin(BASE, f"catalogue/page-{page}.html")

    def parse_list(self, html: str, page_url: str) -> list[str]:
        tree = HTMLParser(html)
        return [
            urljoin(page_url, a.attributes["href"])
            for a in tree.css("article.product_pod h3 a")
            if a.attributes.get("href")
        ]

    def parse_item(self, html: str, url: str) -> dict[str, Any]:
        tree = HTMLParser(html)
        table = {
            th.text(strip=True): td.text(strip=True)
            for row in tree.css("table.table tr")
            if (th := row.css_first("th")) and (td := row.css_first("td"))
        }
        stock_txt = table.get("Availability", "")
        stock = re.search(r"(\d+)", stock_txt)
        rating_node = tree.css_first("p.star-rating")
        rating_cls = (rating_node.attributes.get("class") or "").split() if rating_node else []
        crumbs = tree.css("ul.breadcrumb li a")

        return {
            "key": url,
            "url": url,
            "title": _text(tree, "div.product_main h1"),
            "price": _text(tree, "div.product_main p.price_color"),
            "in_stock": int(stock.group(1)) if stock else 0,
            "rating": next((RATING[c] for c in rating_cls if c in RATING), None),
            "category": crumbs[-1].text(strip=True) if len(crumbs) >= 3 else None,
            "upc": table.get("UPC"),
        }
