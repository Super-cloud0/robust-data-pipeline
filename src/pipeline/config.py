"""Настройки через переменные окружения / .env. Ничего секретного в коде."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PIPE_", extra="ignore")

    # HTTP
    concurrency: int = 5  # одновременных запросов
    requests_per_second: float = 2.0  # вежливый лимит к сайту
    timeout_s: float = 20.0
    max_retries: int = 4
    retry_wait_initial_s: float = 1.0  # экспоненциальная пауза между повторами
    retry_wait_max_s: float = 30.0
    proxy: str | None = None  # http://user:pass@host:port
    user_agents: list[str] = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    ]

    # Выход
    output_dir: str = "output"
    sqlite_path: str = "output/data.db"
    database_url: str | None = None  # postgresql://user:pass@host:5432/db
    gsheets_credentials: str | None = None  # путь к service-account json
    gsheets_spreadsheet_id: str | None = None


def get_settings() -> Settings:
    return Settings()
