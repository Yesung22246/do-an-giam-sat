"""Đọc cấu hình từ biến môi trường / file .env."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str, default: bool) -> bool:
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "sqlite+aiosqlite:///./monitoring.db"
    )
    alert_webhook_url: str = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    max_concurrent_checks: int = int(os.getenv("MAX_CONCURRENT_CHECKS", "50"))
    # Khi chạy một mình (dev/SQLite): để True cho tiện, tự tạo bảng.
    # Khi ghép chung với Backend API (TV2) trên Postgres: đặt False để TV2 làm
    # chủ việc tạo bảng/migration, tránh 2 service cùng tạo gây xung đột.
    auto_create_tables: bool = _as_bool(os.getenv("AUTO_CREATE_TABLES", ""), True)
    # Tự thêm monitor mẫu khi DB trống (chỉ nên bật khi chạy một mình).
    seed_sample_monitors: bool = _as_bool(os.getenv("SEED_SAMPLE_MONITORS", ""), True)


settings = Settings()
