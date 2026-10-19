"""Kiểu dữ liệu kết quả của 1 lần kiểm tra.

Mọi checker trả về cùng một CheckOutcome để Alert Engine xử lý thống nhất.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models import CheckStatus


@dataclass
class CheckOutcome:
    status: CheckStatus
    response_time_ms: float | None = None
    status_code: int | None = None
    ssl_days_left: int | None = None
    error: str | None = None

    @property
    def is_up(self) -> bool:
        return self.status == CheckStatus.UP

    @classmethod
    def up(cls, **kwargs) -> "CheckOutcome":
        return cls(status=CheckStatus.UP, **kwargs)

    @classmethod
    def down(cls, error: str, **kwargs) -> "CheckOutcome":
        return cls(status=CheckStatus.DOWN, error=error, **kwargs)
