"""Отчёт приёмки для клиента: только измеренные цифры, ничего не выдумываем."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pipeline.base import RunResult
from pipeline.models import Record


@dataclass
class Report:
    source: str
    total_attempted: int
    valid: int
    rejected: int
    duration_s: float
    field_fill: dict[str, float]  # % записей, где поле заполнено
    reject_reasons: dict[str, int]
    http: dict[str, int]

    @property
    def valid_pct(self) -> float:
        return round(100 * self.valid / self.total_attempted, 1) if self.total_attempted else 0.0

    def to_markdown(self) -> str:
        lines = [
            f"# Отчёт по сбору: {self.source}",
            "",
            f"- Обработано карточек: **{self.total_attempted}**",
            f"- Валидных записей в выгрузке: **{self.valid}** ({self.valid_pct}%)",
            f"- Отбраковано: **{self.rejected}** (причины ниже, ничего не потеряно молча)",
            f"- Время прогона: **{self.duration_s:.1f} с**",
            f"- HTTP: запросов {self.http.get('requests', 0)}, "
            f"повторов {self.http.get('retries', 0)}, ошибок {self.http.get('failed', 0)}",
            "",
            "## Заполненность полей (среди валидных записей)",
            "",
            "| Поле | Заполнено |",
            "|---|---|",
        ]
        lines += [f"| {k} | {v}% |" for k, v in self.field_fill.items()]
        if self.reject_reasons:
            lines += ["", "## Причины отбраковки", "", "| Причина | Кол-во |", "|---|---|"]
            lines += [f"| {k} | {v} |" for k, v in self.reject_reasons.items()]
        return "\n".join(lines) + "\n"

    def save(self, out_dir: str | Path, stem: str) -> tuple[Path, Path]:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        md = out / f"{stem}_report.md"
        js = out / f"{stem}_report.json"
        md.write_text(self.to_markdown(), encoding="utf-8")
        payload = {**self.__dict__, "valid_pct": self.valid_pct}
        js.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return md, js


def _filled(v: object) -> bool:
    return v is not None and v != "" and v != [] and v != {}


def _reason_bucket(reason: str) -> str:
    # "invalid: price: Input should be ..." -> "invalid: price"
    head, _, rest = reason.partition(": ")
    if head == "invalid":
        fields = sorted({part.split(":")[0].strip() for part in rest.split(";")})
        return f"invalid: {', '.join(fields)}"
    return head


def build_report(
    source: str,
    model: type[Record],
    result: RunResult,
    duration_s: float,
    http_stats: dict[str, int],
) -> Report:
    fields = model.data_fields()
    n = len(result.records)
    fill = {
        f: round(100 * sum(_filled(getattr(r, f)) for r in result.records) / n, 1) if n else 0.0
        for f in fields
    }
    reasons = Counter(_reason_bucket(r.reason) for r in result.rejected)
    return Report(
        source=source,
        total_attempted=n + len(result.rejected),
        valid=n,
        rejected=len(result.rejected),
        duration_s=duration_s,
        field_fill=fill,
        reject_reasons=dict(reasons.most_common()),
        http=dict(http_stats),
    )
