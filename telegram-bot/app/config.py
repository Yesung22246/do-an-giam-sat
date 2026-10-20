"""Configuration for the TV5 Telegram integration."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "sqlite+aiosqlite:///./monitoring.db"
    )
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_webhook_url: str = os.getenv("TELEGRAM_WEBHOOK_URL", "").strip()
    telegram_webhook_secret: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    telegram_api_base_url: str = os.getenv(
        "TELEGRAM_API_BASE_URL", "https://api.telegram.org"
    ).rstrip("/")
    link_api_key: str = os.getenv("TELEGRAM_LINK_API_KEY", "")
    link_code_ttl_seconds: int = int(os.getenv("TELEGRAM_LINK_CODE_TTL_SECONDS", "600"))
    report_timezone: str = os.getenv("REPORT_TIMEZONE", "Asia/Ho_Chi_Minh")
    daily_report_hour: int = int(os.getenv("REPORT_DAILY_HOUR", "8"))
    weekly_report_day: str = os.getenv("REPORT_WEEKLY_DAY", "mon").strip().lower()
    weekly_report_hour: int = int(os.getenv("REPORT_WEEKLY_HOUR", "8"))
    report_poll_seconds: int = int(os.getenv("REPORT_POLL_SECONDS", "60"))
    auto_create_bot_tables: bool = os.getenv(
        "AUTO_CREATE_BOT_TABLES", "true"
    ).strip().lower() in {"1", "true", "yes", "on"}

    @property
    def report_zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.report_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Múi giờ không hợp lệ: {self.report_timezone}") from exc

    @property
    def weekly_report_weekday(self) -> int:
        weekdays = {"mon": 0, "tue": 1, "wed": 2, "thu": 3,
                    "fri": 4, "sat": 5, "sun": 6}
        try:
            return weekdays[self.weekly_report_day]
        except KeyError as exc:
            raise ValueError("REPORT_WEEKLY_DAY phải là mon, tue, wed, thu, fri, sat hoặc sun") from exc

    def validate(self) -> None:
        if not 1 <= self.link_code_ttl_seconds <= 86400:
            raise ValueError("TELEGRAM_LINK_CODE_TTL_SECONDS phải từ 1 đến 86400")
        if not 0 <= self.daily_report_hour <= 23:
            raise ValueError("REPORT_DAILY_HOUR phải từ 0 đến 23")
        if not 0 <= self.weekly_report_hour <= 23:
            raise ValueError("REPORT_WEEKLY_HOUR phải từ 0 đến 23")
        if self.report_poll_seconds < 10:
            raise ValueError("REPORT_POLL_SECONDS tối thiểu là 10")
        if self.telegram_webhook_url:
            if not self.telegram_webhook_secret:
                raise ValueError("TELEGRAM_WEBHOOK_SECRET là bắt buộc khi bật webhook")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", self.telegram_webhook_secret):
                raise ValueError("TELEGRAM_WEBHOOK_SECRET chỉ được dùng chữ, số, _ và - (tối đa 256 ký tự)")
        _ = self.report_zone
        _ = self.weekly_report_weekday
