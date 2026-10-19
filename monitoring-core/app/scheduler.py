"""Scheduler — vòng lặp giám sát chạy song song nhiều monitor.

Mỗi monitor có 1 vòng lặp riêng chạy đúng chu kỳ (interval) của nó.
Một Semaphore giới hạn số lần kiểm tra chạy đồng thời để không nghẽn khi
có hàng trăm monitor.

Mỗi lần kiểm tra:
  run_check -> lưu CheckResult -> AlertEngine.process -> mở/đóng Incident
  -> đẩy cảnh báo qua Notifier.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .alert_engine import AlertEngine, AlertKind, AlertEvent, AlertPolicy
from .checkers import run_check
from .checkers.base import CheckOutcome
from .database import SessionLocal
from .models import (
    CheckResult,
    CheckStatus,
    Incident,
    IncidentState,
    Monitor,
    MonitorAlertState,
    utcnow,
)
from .notifier import Notifier


class MonitorScheduler:
    def __init__(
        self,
        notifier: Notifier,
        max_concurrent: int = 50,
        policy: AlertPolicy | None = None,
        rollup_interval_seconds: int = 3600,
        raw_retention_hours: int = 48,
    ) -> None:
        self.notifier = notifier
        self.engine = AlertEngine(policy=policy)
        self._sem = asyncio.Semaphore(max_concurrent)
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()
        # Gom dữ liệu cũ định kỳ để DB không phình (mặc định mỗi giờ).
        self.rollup_interval_seconds = rollup_interval_seconds
        self.raw_retention_hours = raw_retention_hours

    async def run_forever(self) -> None:
        """Nạp danh sách monitor rồi chạy mỗi cái một vòng lặp cho tới khi dừng."""
        async with SessionLocal() as session:
            monitors = (
                await session.scalars(select(Monitor).where(Monitor.enabled.is_(True)))
            ).all()

        if not monitors:
            print("[scheduler] Chưa có monitor nào (enabled). Dừng.")
            return

        print(f"[scheduler] Bắt đầu giám sát {len(monitors)} mục tiêu.")
        self._tasks = [
            asyncio.create_task(self._monitor_loop(m.id, m.interval_seconds))
            for m in monitors
        ]
        self._tasks.append(asyncio.create_task(self._rollup_loop()))
        try:
            await self._stop.wait()
        finally:
            for t in self._tasks:
                t.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def stop(self) -> None:
        self._stop.set()

    async def _monitor_loop(self, monitor_id: int, interval: int) -> None:
        while not self._stop.is_set():
            try:
                await self.check_once(monitor_id)
            except Exception as exc:  # không để 1 monitor lỗi làm chết cả vòng
                print(f"[scheduler] Lỗi khi kiểm tra monitor #{monitor_id}: {exc}")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass  # hết interval -> kiểm tra tiếp

    async def _rollup_loop(self) -> None:
        """Định kỳ gom dữ liệu kiểm tra cũ thành rollup theo giờ."""
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.rollup_interval_seconds
                )
            except asyncio.TimeoutError:
                pass
            if self._stop.is_set():
                break
            try:
                async with SessionLocal() as session:
                    moved = await rollup_hourly(
                        session, raw_retention_hours=self.raw_retention_hours
                    )
                if moved:
                    print(f"[rollup] Đã gom {moved} dòng dữ liệu cũ.")
            except Exception as exc:
                print(f"[rollup] Lỗi khi gom dữ liệu: {exc}")

    async def check_once(self, monitor_id: int) -> list[AlertEvent]:
        """Thực hiện đúng 1 lần kiểm tra cho 1 monitor (dùng lại được trong demo/test)."""
        async with self._sem:
            async with SessionLocal() as session:
                monitor = await session.get(Monitor, monitor_id)
                if monitor is None or not monitor.enabled:
                    return []

                # Ngưỡng riêng của từng monitor (không sửa policy dùng chung).
                policy = self._policy_for(monitor)

                # Nạp lại trạng thái alert từ DB nếu engine chưa có trong RAM
                # (xảy ra ngay sau khi service khởi động lại).
                await self._ensure_state_loaded(session, monitor_id)

                outcome = await run_check(monitor)
                now = utcnow()

                await self._save_result(session, monitor_id, outcome, now)
                events = self.engine.process(
                    monitor_id, monitor.name, outcome, now, policy=policy
                )
                await self._apply_incidents(session, monitor_id, events, now)
                await self._save_state(session, monitor_id)
                await session.commit()

        await self.notifier.send_many(events)
        return events

    def _policy_for(self, monitor: Monitor) -> AlertPolicy:
        """Dựng ngưỡng cảnh báo riêng cho 1 monitor từ cấu hình của nó.

        Lấy `retries` và `ssl_warn_days` theo từng monitor; các ngưỡng còn lại
        (recovery, flapping) dùng mặc định của engine. Trả về object MỚI nên
        không ảnh hưởng tới các monitor khác đang chạy song song.
        """
        base = self.engine.policy
        return AlertPolicy(
            retries=monitor.retries,
            recovery_threshold=base.recovery_threshold,
            flap_window=base.flap_window,
            flap_threshold=base.flap_threshold,
            ssl_warn_days=monitor.ssl_warn_days,
        )

    async def _ensure_state_loaded(
        self, session: AsyncSession, monitor_id: int
    ) -> None:
        """Nếu engine chưa giữ state của monitor này trong RAM thì nạp từ DB."""
        if self.engine.has_state(monitor_id):
            return
        row = await session.get(MonitorAlertState, monitor_id)
        if row is not None:
            self.engine.load_state(
                monitor_id,
                {
                    "confirmed": row.confirmed.value,
                    "consecutive_failures": row.consecutive_failures,
                    "consecutive_successes": row.consecutive_successes,
                    "transitions": row.transitions or [],
                    "flapping_active": row.flapping_active,
                    "ssl_notified": row.ssl_notified,
                    "last_cause": row.last_cause,
                },
            )

    async def _save_state(self, session: AsyncSession, monitor_id: int) -> None:
        """Lưu trạng thái alert hiện tại xuống DB (upsert 1 dòng/monitor)."""
        data = self.engine.dump_state(monitor_id)
        if data is None:
            return
        row = await session.get(MonitorAlertState, monitor_id)
        if row is None:
            row = MonitorAlertState(monitor_id=monitor_id)
            session.add(row)
        row.confirmed = CheckStatus(data["confirmed"])
        row.consecutive_failures = data["consecutive_failures"]
        row.consecutive_successes = data["consecutive_successes"]
        row.transitions = data["transitions"]
        row.flapping_active = data["flapping_active"]
        row.ssl_notified = data["ssl_notified"]
        row.last_cause = data["last_cause"]
        row.updated_at = utcnow()

    async def _save_result(
        self,
        session: AsyncSession,
        monitor_id: int,
        outcome: CheckOutcome,
        now: datetime,
    ) -> None:
        session.add(
            CheckResult(
                monitor_id=monitor_id,
                checked_at=now,
                status=outcome.status,
                response_time_ms=outcome.response_time_ms,
                status_code=outcome.status_code,
                ssl_days_left=outcome.ssl_days_left,
                error=outcome.error,
            )
        )

    async def _apply_incidents(
        self,
        session: AsyncSession,
        monitor_id: int,
        events: list[AlertEvent],
        now: datetime,
    ) -> None:
        """Mở/đóng Incident theo loại sự kiện (nguồn dữ liệu 'lịch sử sự cố')."""
        for event in events:
            if event.kind == AlertKind.DOWN:
                await self._open_incident(
                    session, monitor_id, now, event.message, "critical"
                )
            elif event.kind == AlertKind.FLAPPING:
                await self._open_incident(
                    session, monitor_id, now, event.message, "warning"
                )
            elif event.kind in (AlertKind.RECOVERED, AlertKind.STABILIZED):
                await self._resolve_open_incidents(session, monitor_id, now)

    async def _open_incident(
        self,
        session: AsyncSession,
        monitor_id: int,
        now: datetime,
        cause: str,
        severity: str,
    ) -> None:
        existing = await session.scalar(
            select(Incident).where(
                Incident.monitor_id == monitor_id,
                Incident.state == IncidentState.OPEN,
            )
        )
        if existing is not None:
            return  # đã có sự cố đang mở -> không tạo trùng
        session.add(
            Incident(
                monitor_id=monitor_id,
                state=IncidentState.OPEN,
                started_at=now,
                cause=cause,
                severity=severity,
            )
        )

    async def _resolve_open_incidents(
        self, session: AsyncSession, monitor_id: int, now: datetime
    ) -> None:
        open_incidents = (
            await session.scalars(
                select(Incident).where(
                    Incident.monitor_id == monitor_id,
                    Incident.state == IncidentState.OPEN,
                )
            )
        ).all()
        for inc in open_incidents:
            inc.state = IncidentState.RESOLVED
            inc.resolved_at = now
