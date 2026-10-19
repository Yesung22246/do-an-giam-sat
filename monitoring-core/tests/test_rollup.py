"""Test gom dữ liệu (rollup) + uptime gộp cả rollup lẫn dữ liệu thô."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base, CheckResult, CheckRollup, CheckStatus, Monitor, MonitorType
from app.rollup import rollup_hourly
from app.uptime import compute_uptime

NOW = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # SQLite in-memory dùng chung 1 kết nối (StaticPool) để dữ liệu còn mãi.
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _make_monitor(s: AsyncSession) -> int:
    m = Monitor(name="t", type=MonitorType.HTTP, target="https://x")
    s.add(m)
    await s.commit()
    return m.id


async def _add_check(s, mid, when, up=True, ms=100.0):
    s.add(
        CheckResult(
            monitor_id=mid,
            checked_at=when,
            status=CheckStatus.UP if up else CheckStatus.DOWN,
            response_time_ms=ms if up else None,
        )
    )


async def test_rollup_groups_old_and_keeps_recent(session):
    mid = await _make_monitor(session)
    # 3 lần cũ (5 ngày trước, cùng 1 giờ): 2 UP + 1 DOWN
    old_hour = NOW - timedelta(days=5)
    await _add_check(session, mid, old_hour.replace(minute=5), up=True, ms=100)
    await _add_check(session, mid, old_hour.replace(minute=25), up=True, ms=300)
    await _add_check(session, mid, old_hour.replace(minute=45), up=False)
    # 1 lần gần đây (10 phút trước) -> phải GIỮ nguyên dạng thô
    await _add_check(session, mid, NOW - timedelta(minutes=10), up=True, ms=120)
    await session.commit()

    moved = await rollup_hourly(session, raw_retention_hours=48, now=NOW)
    assert moved == 3  # 3 dòng cũ được gom

    # Dữ liệu thô: chỉ còn 1 dòng gần đây
    raw_left = await session.scalar(select(func.count(CheckResult.id)))
    assert raw_left == 1

    # Có đúng 1 dòng rollup, tổng hợp đúng
    roll = await session.scalar(select(CheckRollup))
    assert roll.total_checks == 3
    assert roll.up_checks == 2
    assert roll.down_checks == 1
    assert roll.uptime_percent == round(100 * 2 / 3, 3)
    assert roll.min_response_ms == 100.0
    assert roll.max_response_ms == 300.0


async def test_uptime_combines_rollup_and_raw(session):
    mid = await _make_monitor(session)
    old_hour = NOW - timedelta(days=5)
    await _add_check(session, mid, old_hour.replace(minute=5), up=True, ms=100)
    await _add_check(session, mid, old_hour.replace(minute=25), up=False)
    await _add_check(session, mid, NOW - timedelta(minutes=10), up=True, ms=200)
    await session.commit()

    # Trước khi gom: uptime 30 ngày = 2 UP / 3 = 66.667%
    before = await compute_uptime(session, mid, window_hours=24 * 30, now=NOW)
    assert before.total_checks == 3 and before.up_checks == 2

    await rollup_hourly(session, raw_retention_hours=48, now=NOW)

    # Sau khi gom: uptime 30 ngày PHẢI vẫn bằng 66.667% (không hụt dữ liệu)
    after = await compute_uptime(session, mid, window_hours=24 * 30, now=NOW)
    assert after.total_checks == 3
    assert after.up_checks == 2
    assert after.uptime_percent == before.uptime_percent


async def test_rollup_noop_when_nothing_old(session):
    mid = await _make_monitor(session)
    await _add_check(session, mid, NOW - timedelta(minutes=5), up=True)
    await session.commit()
    moved = await rollup_hourly(session, raw_retention_hours=48, now=NOW)
    assert moved == 0
