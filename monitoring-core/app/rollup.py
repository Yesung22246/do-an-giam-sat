"""Gom dữ liệu kiểm tra cũ theo giờ để biểu đồ dài ngày không phình DB.

Cách dùng: gọi định kỳ (vd mỗi giờ) `rollup_hourly(session)`.
- Giữ nguyên dữ liệu thô `check_results` trong `raw_retention_hours` gần nhất.
- Phần cũ hơn: gom thành 1 dòng/giờ trong `check_rollups` rồi xóa dòng thô.

Gom bằng Python (thay vì SQL GROUP BY) để chạy giống nhau trên cả SQLite lẫn
Postgres — đủ tốt cho đồ án; nếu dữ liệu cực lớn thì chuyển sang GROUP BY phía DB.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CheckResult, CheckRollup, CheckStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hour_floor(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


async def rollup_hourly(
    session: AsyncSession,
    raw_retention_hours: int = 48,
    now: datetime | None = None,
) -> int:
    """Gom các dòng thô cũ hơn mốc giữ lại thành rollup theo giờ.

    Trả về số dòng thô đã được gom (và xóa). An toàn khi gọi lặp lại: chỉ xử lý
    các khung giờ đã khép kín (cũ hơn mốc), nên không gom nhầm giờ đang chạy dở.
    """
    now = now or _utcnow()
    # Chỉ gom những giờ đã khép kín hẳn (nhỏ hơn mốc, cắt tròn về đầu giờ).
    cutoff = _hour_floor(now - timedelta(hours=raw_retention_hours))

    old_rows = (
        await session.scalars(
            select(CheckResult).where(CheckResult.checked_at < cutoff)
        )
    ).all()
    if not old_rows:
        return 0

    # Nhóm theo (monitor_id, đầu giờ).
    buckets: dict[tuple[int, datetime], list[CheckResult]] = defaultdict(list)
    for r in old_rows:
        buckets[(r.monitor_id, _hour_floor(r.checked_at))].append(r)

    for (monitor_id, bucket_start), rows in buckets.items():
        total = len(rows)
        up = sum(1 for r in rows if r.status == CheckStatus.UP)
        down = total - up
        resp = [r.response_time_ms for r in rows if r.response_time_ms is not None]
        avg_ms = round(sum(resp) / len(resp), 1) if resp else None
        min_ms = round(min(resp), 1) if resp else None
        max_ms = round(max(resp), 1) if resp else None
        uptime = round(100.0 * up / total, 3) if total else 100.0

        existing = await session.scalar(
            select(CheckRollup).where(
                CheckRollup.monitor_id == monitor_id,
                CheckRollup.bucket_start == bucket_start,
            )
        )
        if existing is None:
            session.add(
                CheckRollup(
                    monitor_id=monitor_id,
                    bucket_start=bucket_start,
                    total_checks=total,
                    up_checks=up,
                    down_checks=down,
                    uptime_percent=uptime,
                    avg_response_ms=avg_ms,
                    min_response_ms=min_ms,
                    max_response_ms=max_ms,
                )
            )
        else:
            # Gộp thêm vào rollup đã có (trường hợp gọi lại giữa chừng).
            existing.total_checks += total
            existing.up_checks += up
            existing.down_checks += down
            existing.uptime_percent = round(
                100.0 * existing.up_checks / existing.total_checks, 3
            )
            _merge_response(existing, avg_ms, min_ms, max_ms, up)

    # Xóa dữ liệu thô đã gom. synchronize_session=False: xóa thẳng dưới DB,
    # không để ORM so khớp lại các object trong session (tránh lỗi so sánh
    # datetime có-tz vs không-tz khi SQLite trả về datetime naive).
    await session.execute(
        delete(CheckResult)
        .where(CheckResult.checked_at < cutoff)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return len(old_rows)


def _merge_response(existing, avg_ms, min_ms, max_ms, new_up) -> None:
    if min_ms is not None:
        existing.min_response_ms = (
            min_ms if existing.min_response_ms is None
            else min(existing.min_response_ms, min_ms)
        )
    if max_ms is not None:
        existing.max_response_ms = (
            max_ms if existing.max_response_ms is None
            else max(existing.max_response_ms, max_ms)
        )
    if avg_ms is not None:
        if existing.avg_response_ms is None:
            existing.avg_response_ms = avg_ms
        else:
            # Trung bình có trọng số thô (đủ dùng cho biểu đồ).
            existing.avg_response_ms = round((existing.avg_response_ms + avg_ms) / 2, 1)
