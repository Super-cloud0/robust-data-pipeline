from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pytest
from conftest import books_transport

from pipeline import storage
from pipeline.base import Rejected, RunResult
from pipeline.report import build_report
from pipeline.sources.books_demo import Book, BooksDemoScraper


def _book(key: str, title: str = "T", price: str = "10.00") -> Book:
    return Book(key=key, url=key, title=title, price=price, in_stock=1, rating=5)


def test_sqlite_upsert_is_idempotent(tmp_path):
    db = tmp_path / "d.db"
    storage.upsert_sqlite([_book("https://x.kz/1"), _book("https://x.kz/2")], db, "books")
    # повторный прогон с изменённой ценой не плодит дубли, а обновляет
    storage.upsert_sqlite([_book("https://x.kz/1", price="12.50")], db, "books")
    with sqlite3.connect(db) as con:
        rows = dict(con.execute("SELECT key, price FROM books").fetchall())
    assert len(rows) == 2
    assert rows["https://x.kz/1"] == "12.50"


def test_rejects_bad_table_name(tmp_path):
    with pytest.raises(ValueError):
        storage.upsert_sqlite([_book("https://x.kz/1")], tmp_path / "d.db", "books; DROP")


def test_csv_and_xlsx(tmp_path):
    recs = [_book("https://x.kz/1", title="Кириллица")]
    p = storage.write_csv(recs, tmp_path / "a.csv")
    with p.open(encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f))
    assert row["title"] == "Кириллица"
    assert storage.write_xlsx(recs, tmp_path / "a.xlsx").exists()


def test_report_counts_are_measured():
    result = RunResult(
        records=[_book("https://x.kz/1"), _book("https://x.kz/2")],
        rejected=[Rejected("u", "invalid: price: bad; title: missing")],
    )
    rep = build_report("books", Book, result, 1.5, {"requests": 3})
    assert rep.total_attempted == 3
    assert rep.valid == 2
    assert rep.valid_pct == 66.7
    assert rep.field_fill["title"] == 100.0
    assert rep.field_fill["category"] == 0.0
    assert rep.reject_reasons == {"invalid: price, title": 1}
    assert "Отбраковано: **1**" in rep.to_markdown()


async def test_end_to_end_run(settings):
    from pipeline import cli

    transport, _ = books_transport()
    code = await cli.run_once(
        BooksDemoScraper.name, None, ["csv", "xlsx", "sqlite"], settings, transport=transport
    )
    assert code == 0
    out = Path(settings.output_dir)
    suffixes = {p.suffix for p in out.iterdir()}
    assert {".csv", ".xlsx", ".md", ".json", ".db"} <= suffixes
    assert any(p.name.endswith("_rejected.csv") for p in out.iterdir())
