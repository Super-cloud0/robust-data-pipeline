"""Базовая модель записи. Каждый источник наследует её и описывает свои поля."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    """Одна строка выгрузки.

    - `key` - уникальный идентификатор (обычно URL или артикул), по нему идёт upsert.
    - `scraped_at` - когда собрано.
    Поля, обязательные для клиента, объявляйте без значения по умолчанию:
    запись без них не пройдёт валидацию и попадёт в rejected, а не в выгрузку.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    key: str = Field(min_length=1)
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def data_fields(cls) -> list[str]:
        """Поля, по которым считается заполненность в отчёте (без служебных)."""
        return [f for f in cls.model_fields if f not in {"scraped_at"}]
