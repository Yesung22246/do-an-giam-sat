"""Test scheduler tự đồng bộ danh sách monitor với DB.

Khi ghép với Backend API (TV2), khách thêm/sửa/xóa/tắt monitor qua web bất cứ
lúc nào; scheduler phải tự nhận ra mà không cần khởi động lại.
"""
from __future__ import annotations

import asyncio

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.scheduler as scheduler_module
from app.models import Base, Monitor, MonitorType
from app.notifier import ConsoleNotifier
from app.scheduler import MonitorScheduler


@pytest_asyncio.fixture
async def maker(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(scheduler_module, "SessionLocal", session_maker)
    yield session_maker
    await engine.dispose()


def _scheduler() -> MonitorScheduler:
    sch = MonitorScheduler(ConsoleNotifier())

    async def no_network_check(monitor_id: int):  # không gọi mạng trong test
        return []

    sch.check_once = no_network_check
    return sch


async def _add(maker, name: str, enabled: bool = True, interval: int = 60) -> int:
    async with maker() as s:
        m = Monitor(
            name=name, type=MonitorType.HTTP, target="https://x",
            enabled=enabled, interval_seconds=interval,
        )
        s.add(m)
        await s.commit()
        return m.id


async def _set(maker, monitor_id: int, **fields) -> None:
    async with maker() as s:
        m = await s.get(Monitor, monitor_id)
        for k, v in fields.items():
            setattr(m, k, v)
        await s.commit()


async def _stop_all(sch: MonitorScheduler) -> None:
    tasks = [t for t, _ in sch._loops.values()]
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_empty_db_does_not_crash(maker):
    sch = _scheduler()
    await sch.sync_monitors()
    assert sch.active_monitor_ids == set()


async def test_picks_up_only_enabled_monitors(maker):
    a = await _add(maker, "a")
    b = await _add(maker, "b")
    await _add(maker, "tắt", enabled=False)
    sch = _scheduler()
    await sch.sync_monitors()
    assert sch.active_monitor_ids == {a, b}
    await _stop_all(sch)


async def test_new_monitor_added_later_is_picked_up(maker):
    a = await _add(maker, "a")
    sch = _scheduler()
    await sch.sync_monitors()
    assert sch.active_monitor_ids == {a}

    b = await _add(maker, "khách vừa thêm qua web")
    await sch.sync_monitors()
    assert sch.active_monitor_ids == {a, b}
    await _stop_all(sch)


async def test_disabled_or_deleted_monitor_is_stopped(maker):
    a = await _add(maker, "a")
    b = await _add(maker, "b")
    sch = _scheduler()
    await sch.sync_monitors()

    await _set(maker, a, enabled=False)          # khách tắt monitor
    async with maker() as s:                     # khách xóa monitor
        await s.delete(await s.get(Monitor, b))
        await s.commit()

    await sch.sync_monitors()
    assert sch.active_monitor_ids == set()


async def test_interval_change_restarts_loop(maker):
    a = await _add(maker, "a", interval=60)
    sch = _scheduler()
    await sch.sync_monitors()
    old_task, old_interval = sch._loops[a]
    assert old_interval == 60

    await _set(maker, a, interval_seconds=30)    # khách đổi chu kỳ
    await sch.sync_monitors()
    new_task, new_interval = sch._loops[a]
    assert new_interval == 30
    assert new_task is not old_task
    await asyncio.sleep(0)
    assert old_task.cancelled() or old_task.done()
    await _stop_all(sch)
