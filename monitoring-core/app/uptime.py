"""Tính uptime và thời gian phản hồi trung bình từ lịch sử kiểm tra."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CheckResult, CheckStatus, utcnow


@dataclass
class UptimeStats:
    monitor_id: int
    window_hours: int
    total_checks: int
    up_checks: int
    uptime_percent: float
    avg_response_ms: float | None


async def compute_uptime(
    session: AsyncSession, monitor_id: int, window_hours: int = 24
) -> UptimeStats:
    """Tỷ lệ uptime = số lần UP / tổng số lần kiểm tra trong cửa sổ thời gian."""
    since = utcnow() - timedelta(hours=window_hours)

    total = await session.scalar(
        select(func.count(CheckResult.id)).where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= since,
        )
    ) or 0
    up = await session.scalar(
        select(func.count(CheckResult.id)).where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= since,
            CheckResult.status == CheckStatus.UP,
        )
    ) or 0
    avg_ms = await session.scalar(
        select(func.avg(CheckResult.response_time_ms)).where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= since,
            CheckResult.status == CheckStatus.UP,
        )
    )

    percent = round(100.0 * up / total, 3) if total else 100.0
    return UptimeStats(
        monitor_id=monitor_id,
        window_hours=window_hours,
        total_checks=total,
        up_checks=up,
        uptime_percent=percent,
        avg_response_ms=round(avg_ms, 1) if avg_ms is not None else None,
    )
