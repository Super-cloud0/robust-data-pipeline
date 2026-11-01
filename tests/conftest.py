from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from pipeline.config import Settings

FIX = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        concurrency=4,
        requests_per_second=0,  # в тестах без пауз
        max_retries=3,
        retry_wait_initial_s=0,
        retry_wait_max_s=0,
        output_dir=str(tmp_path / "out"),
        sqlite_path=str(tmp_path / "out" / "data.db"),
        _env_file=None,
    )


def books_transport(fail_first: int = 0) -> tuple[httpx.MockTransport, dict[str, int]]:
    """Сайт-заглушка без сети: 1 страница каталога, 2 карточки (одна битая).

    fail_first - сколько первых запросов к карточке вернуть 503 (проверка ретраев).
    """
    calls = {"item": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("catalogue/page-1.html"):
            return httpx.Response(200, text=fixture("books_list.html"))
        if path.startswith("/catalogue/page-"):
            return httpx.Response(404)
        if "a-light-in-the-attic" in path:
            calls["item"] += 1
            if calls["item"] <= fail_first:
                return httpx.Response(503)
            return httpx.Response(200, text=fixture("books_item.html"))
        if "broken-book" in path:
            return httpx.Response(200, text=fixture("books_item_broken.html"))
        return httpx.Response(404)

    return httpx.MockTransport(handler), calls
