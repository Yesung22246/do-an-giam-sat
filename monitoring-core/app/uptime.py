"""Tính uptime và thời gian phản hồi trung bình từ lịch sử kiểm tra.

Gộp cả 2 nguồn để số liệu không bị hụt sau khi dữ liệu cũ đã được gom (rollup):
- check_results : dữ liệu thô gần đây (còn giữ lại).
- check_rollups : dữ liệu cũ đã gom theo giờ.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CheckResult, CheckRollup, CheckStatus, utcnow


@dataclass
class UptimeStats:
    monitor_id: int
    window_hours: int
    total_checks: int
    up_checks: int
    uptime_percent: float
    avg_response_ms: float | None


async def compute_uptime(
    session: AsyncSession,
    monitor_id: int,
    window_hours: int = 24,
    now: datetime | None = None,
) -> UptimeStats:
    """Tỷ lệ uptime = tổng số lần UP / tổng số lần kiểm tra trong cửa sổ.

    Cộng dồn từ cả dữ liệu thô và dữ liệu đã gom (rollup) để kết quả đúng kể cả
    với cửa sổ dài (vd 30 ngày) khi phần lớn dữ liệu đã bị gom.
    """
    since = (now or utcnow()) - timedelta(hours=window_hours)

    # --- Nguồn 1: dữ liệu thô gần đây ---
    raw_total = await session.scalar(
        select(func.count(CheckResult.id)).where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= since,
        )
    ) or 0
    raw_up = await session.scalar(
        select(func.count(CheckResult.id)).where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= since,
            CheckResult.status == CheckStatus.UP,
        )
    ) or 0
    raw_resp_sum = await session.scalar(
        select(func.sum(CheckResult.response_time_ms)).where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= since,
            CheckResult.status == CheckStatus.UP,
        )
    ) or 0.0

    # --- Nguồn 2: dữ liệu đã gom theo giờ ---
    roll_total = await session.scalar(
        select(func.sum(CheckRollup.total_checks)).where(
            CheckRollup.monitor_id == monitor_id,
            CheckRollup.bucket_start >= since,
        )
    ) or 0
    roll_up = await session.scalar(
        select(func.sum(CheckRollup.up_checks)).where(
            CheckRollup.monitor_id == monitor_id,
            CheckRollup.bucket_start >= since,
        )
    ) or 0
    # Tổng thời gian phản hồi ≈ avg_response_ms * up_checks của từng khung giờ.
    roll_resp_sum = await session.scalar(
        select(
            func.sum(CheckRollup.avg_response_ms * CheckRollup.up_checks)
        ).where(
            CheckRollup.monitor_id == monitor_id,
            CheckRollup.bucket_start >= since,
            CheckRollup.avg_response_ms.is_not(None),
        )
    ) or 0.0

    total = raw_total + roll_total
    up = raw_up + roll_up
    resp_sum = (raw_resp_sum or 0.0) + (roll_resp_sum or 0.0)

    percent = round(100.0 * up / total, 3) if total else 100.0
    avg_ms = round(resp_sum / up, 1) if up else None
    return UptimeStats(
        monitor_id=monitor_id,
        window_hours=window_hours,
        total_checks=total,
        up_checks=up,
        uptime_percent=percent,
        avg_response_ms=avg_ms,
    )
