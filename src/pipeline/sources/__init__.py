"""Реестр источников. Новый источник: создать файл рядом и добавить в SOURCES."""

from __future__ import annotations

from pipeline.base import BaseScraper
from pipeline.sources.books_demo import BooksDemoScraper

SOURCES: dict[str, type[BaseScraper]] = {
    BooksDemoScraper.name: BooksDemoScraper,
}
