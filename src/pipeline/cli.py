"""CLI.

pipeline list
pipeline run books_demo --limit 50 --out csv xlsx sqlite
pipeline schedule books_demo --cron "0 */6 * * *" --out sqlite
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

from pipeline import storage
from pipeline.config import Settings, get_settings
from pipeline.http import Fetcher
from pipeline.report import build_report
from pipeline.sources import SOURCES

log = logging.getLogger("pipeline")
OUTPUTS = ("csv", "xlsx", "sqlite", "postgres", "gsheets")


async def run_once(
    source: str,
    limit: int | None,
    outputs: list[str],
    s: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    cls = SOURCES[source]
    started = time.monotonic()
    async with Fetcher(s, transport=transport) as fetcher:
        result = await cls(fetcher).run(limit=limit)
        stats = fetcher.stats
    duration = time.monotonic() - started

    stem = f"{source}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir = Path(s.output_dir)
    recs = result.records

    if "csv" in outputs:
        log.info("CSV: %s", storage.write_csv(recs, out_dir / f"{stem}.csv"))
    if "xlsx" in outputs:
        log.info("XLSX: %s", storage.write_xlsx(recs, out_dir / f"{stem}.xlsx"))
    if "sqlite" in outputs:
        n = storage.upsert_sqlite(recs, s.sqlite_path, source)
        log.info("SQLite: upsert %d -> %s", n, s.sqlite_path)
    if "postgres" in outputs:
        if not s.database_url:
            raise SystemExit("PIPE_DATABASE_URL не задан")
        log.info("Postgres: upsert %d", storage.upsert_postgres(recs, s.database_url, source))
    if "gsheets" in outputs:
        if not (s.gsheets_credentials and s.gsheets_spreadsheet_id):
            raise SystemExit("PIPE_GSHEETS_CREDENTIALS / PIPE_GSHEETS_SPREADSHEET_ID не заданы")
        n = storage.write_gsheets(recs, s.gsheets_credentials, s.gsheets_spreadsheet_id, source)
        log.info("Google Sheets: %d строк", n)

    if result.rejected:
        rej = out_dir / f"{stem}_rejected.csv"
        rej.parent.mkdir(parents=True, exist_ok=True)
        with rej.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["url", "reason"])
            w.writerows([r.url, r.reason] for r in result.rejected)
        log.info("Отбраковка: %s", rej)

    report = build_report(source, cls.record_model, result, duration, stats)
    md, _ = report.save(out_dir, stem)
    print(report.to_markdown())
    log.info("Отчёт: %s", md)
    return 0 if report.valid else 1


def schedule(source: str, cron: str, limit: int | None, outputs: list[str], s: Settings) -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    sched = BlockingScheduler()

    def job() -> None:
        try:
            asyncio.run(run_once(source, limit, outputs, s))
        except Exception:  # noqa: BLE001 - один упавший прогон не останавливает расписание
            log.exception("прогон упал")

    sched.add_job(job, CronTrigger.from_crontab(cron), max_instances=1, coalesce=True)
    log.info("расписание '%s' для %s, первый прогон сейчас", cron, source)
    job()
    sched.start()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pipeline")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="список источников")

    for name in ("run", "schedule"):
        sp = sub.add_parser(name)
        sp.add_argument("source", choices=sorted(SOURCES))
        sp.add_argument("--limit", type=int, default=None, help="сколько карточек собрать")
        sp.add_argument("--out", nargs="+", choices=OUTPUTS, default=["csv", "sqlite"])
        if name == "schedule":
            sp.add_argument("--cron", required=True, help='например "0 */6 * * *"')

    a = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not a.verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
    s = get_settings()

    if a.cmd == "list":
        for k in sorted(SOURCES):
            print(k)
        return 0
    if a.cmd == "run":
        return asyncio.run(run_once(a.source, a.limit, a.out, s))
    schedule(a.source, a.cron, a.limit, a.out, s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
