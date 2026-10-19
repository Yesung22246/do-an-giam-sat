"""Đọc cấu hình từ biến môi trường / file .env."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "sqlite+aiosqlite:///./monitoring.db"
    )
    alert_webhook_url: str = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    max_concurrent_checks: int = int(os.getenv("MAX_CONCURRENT_CHECKS", "50"))


settings = Settings()
