"""Выгрузка: CSV, XLSX, SQLite/Postgres (идемпотентный upsert по key), Google Sheets."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pipeline.models import Record

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def to_rows(records: Sequence[Record]) -> tuple[list[str], list[dict[str, Any]]]:
    """Плоские строки (JSON-совместимые значения) + порядок колонок из модели."""
    if not records:
        return [], []
    fields = list(type(records[0]).model_fields)
    # клиенту сначала данные, служебные поля в конце
    service = ["key", "scraped_at"]
    columns = [f for f in fields if f not in service] + service
    rows = [r.model_dump(mode="json") for r in records]
    return columns, rows


def _check_ident(*names: str) -> None:
    for n in names:
        if not _IDENT.match(n):
            raise ValueError(f"недопустимое имя таблицы/колонки: {n!r}")


def write_csv(records: Sequence[Record], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns, rows = to_rows(records)
    # utf-8-sig - чтобы Excel у клиента открыл кириллицу без кракозябр
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
    return path


def write_xlsx(records: Sequence[Record], path: str | Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns, rows = to_rows(records)
    wb = Workbook()
    ws = wb.active
    ws.title = "data"
    ws.append(columns)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="305496")
    for r in rows:
        ws.append([r.get(c) for c in columns])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, c in enumerate(columns, 1):
        width = max([len(str(c))] + [len(str(r.get(c) or "")) for r in rows[:200]])
        ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 8), 60)
    wb.save(path)
    return path


def _upsert_sql(table: str, columns: list[str], placeholder: str) -> tuple[str, str]:
    _check_ident(table, *columns)
    cols_def = ", ".join(f"{c} TEXT" + (" PRIMARY KEY" if c == "key" else "") for c in columns)
    create = f"CREATE TABLE IF NOT EXISTS {table} ({cols_def})"
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c != "key")
    insert = (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join([placeholder] * len(columns))}) "
        f"ON CONFLICT (key) DO UPDATE SET {updates}"
    )
    return create, insert


def _cell(v: Any) -> Any:
    return json.dumps(v, ensure_ascii=False) if isinstance(v, dict | list) else v


def upsert_sqlite(records: Sequence[Record], db_path: str | Path, table: str) -> int:
    columns, rows = to_rows(records)
    if not rows:
        return 0
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    create, insert = _upsert_sql(table, columns, "?")
    with sqlite3.connect(db_path) as con:
        con.execute(create)
        con.executemany(insert, [[_cell(r.get(c)) for c in columns] for r in rows])
    return len(rows)


def upsert_postgres(records: Sequence[Record], database_url: str, table: str) -> int:
    import psycopg  # extras: pip install .[postgres]

    columns, rows = to_rows(records)
    if not rows:
        return 0
    create, insert = _upsert_sql(table, columns, "%s")
    with psycopg.connect(database_url) as con, con.cursor() as cur:
        cur.execute(create)
        cur.executemany(insert, [[_cell(r.get(c)) for c in columns] for r in rows])
    return len(rows)


def write_gsheets(
    records: Sequence[Record], credentials: str, spreadsheet_id: str, worksheet: str
) -> int:
    import gspread  # extras: pip install .[gsheets]

    columns, rows = to_rows(records)
    gc = gspread.service_account(filename=credentials)
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(worksheet)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(worksheet, rows=len(rows) + 10, cols=len(columns) + 2)
    ws.clear()
    ws.update([columns] + [[_cell(r.get(c)) for c in columns] for r in rows])
    return len(rows)
