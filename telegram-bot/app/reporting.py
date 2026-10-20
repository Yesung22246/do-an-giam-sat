"""Statistics and report-period scheduling for linked users."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from .bot_models import ReportDelivery
from .config import Settings
from .shared_models import CheckResult, CheckRollup, Incident, Monitor, NotificationChannel


@dataclass
class MonitorStats:
    monitor_id: int
    name: str
    total_checks: int = 0
    up_checks: int = 0
    response_sum_ms: float = 0.0
    response_count: int = 0
    opened_incidents: int = 0
    resolved_incidents: int = 0
    open_incidents: int = 0

    @property
    def uptime_percent(self) -> float | None:
        if not self.total_checks:
            return None
        return round(self.up_checks * 100 / self.total_checks, 2)

    @property
    def avg_response_ms(self) -> float | None:
        if not self.response_count:
            return None
        return round(self.response_sum_ms / self.response_count, 1)


@dataclass
class UserReport:
    user_id: int
    start: datetime
    end: datetime
    monitors: list[MonitorStats] = field(default_factory=list)

    @property
    def total_checks(self) -> int:
        return sum(item.total_checks for item in self.monitors)

    @property
    def up_checks(self) -> int:
        return sum(item.up_checks for item in self.monitors)

    @property
    def uptime_percent(self) -> float | None:
        if not self.total_checks:
            return None
        return round(self.up_checks * 100 / self.total_checks, 2)

    @property
    def avg_response_ms(self) -> float | None:
        count = sum(item.response_count for item in self.monitors)
        if not count:
            return None
        total = sum(item.response_sum_ms for item in self.monitors)
        return round(total / count, 1)

    @property
    def opened_incidents(self) -> int:
        return sum(item.opened_incidents for item in self.monitors)

    @property
    def resolved_incidents(self) -> int:
        return sum(item.resolved_incidents for item in self.monitors)

    @property
    def open_incidents(self) -> int:
        return sum(item.open_incidents for item in self.monitors)


def _status(value: object) -> str:
    return str(getattr(value, "value", value)).lower().split(".")[-1]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


async def collect_user_report(
    session: AsyncSession, user_id: int, start: datetime, end: datetime
) -> UserReport:
    """Aggregate checks and incident counts for monitors owned by one user."""
    monitor_rows = (
        await session.execute(
            select(Monitor.id, Monitor.name).where(Monitor.owner_id == user_id)
        )
    ).all()
    stats = {row.id: MonitorStats(monitor_id=row.id, name=row.name) for row in monitor_rows}
    if not stats:
        return UserReport(user_id=user_id, start=start, end=end)

    ids = list(stats)
    for monitor_id, status, response_ms in (
        await session.execute(
            select(CheckResult.monitor_id, CheckResult.status, CheckResult.response_time_ms)
            .where(
                CheckResult.monitor_id.in_(ids),
                CheckResult.checked_at >= start,
                CheckResult.checked_at < end,
            )
        )
    ).all():
        item = stats[monitor_id]
        item.total_checks += 1
        if _status(status) == "up":
            item.up_checks += 1
            if response_ms is not None:
                item.response_sum_ms += float(response_ms)
                item.response_count += 1

    # The core retains recent raw checks and folds older checks into hourly
    # buckets. Include both sources so weekly reports remain complete. The core
    # rollup stores average latency but not its sample count; weight by UP count,
    # matching the existing uptime helper's approximation.
    for monitor_id, total_checks, up_checks, avg_response_ms in (
        await session.execute(
            select(
                CheckRollup.monitor_id,
                CheckRollup.total_checks,
                CheckRollup.up_checks,
                CheckRollup.avg_response_ms,
            ).where(
                CheckRollup.monitor_id.in_(ids),
                CheckRollup.bucket_start >= start,
                CheckRollup.bucket_start < end,
            )
        )
    ).all():
        item = stats[monitor_id]
        item.total_checks += total_checks
        item.up_checks += up_checks
        if avg_response_ms is not None and up_checks:
            item.response_sum_ms += float(avg_response_ms) * up_checks
            item.response_count += up_checks

    start_utc, end_utc = _utc(start), _utc(end)
    for monitor_id, state, started_at, resolved_at in (
        await session.execute(
            select(Incident.monitor_id, Incident.state, Incident.started_at, Incident.resolved_at)
            .where(Incident.monitor_id.in_(ids))
        )
    ).all():
        item = stats[monitor_id]
        if _utc(started_at) >= start_utc and _utc(started_at) < end_utc:
            item.opened_incidents += 1
        if resolved_at is not None and _utc(resolved_at) >= start_utc and _utc(resolved_at) < end_utc:
            item.resolved_incidents += 1
        if _status(state) == "open":
            item.open_incidents += 1

    return UserReport(user_id=user_id, start=start, end=end, monitors=list(stats.values()))


def format_report(report: UserReport, title: str, zone: ZoneInfo) -> str:
    local_start = report.start.astimezone(zone)
    local_end = report.end.astimezone(zone)
    lines = [
        f"📊 Báo cáo {title}",
        f"Khoảng: {local_start:%d/%m %H:%M} – {local_end:%d/%m %H:%M}",
        f"Monitor: {len(report.monitors)} | lượt kiểm tra: {report.total_checks}",
        f"Uptime: {_percent(report.uptime_percent)} | phản hồi TB: {_ms(report.avg_response_ms)}",
        f"Sự cố mới: {report.opened_incidents} | đã phục hồi: {report.resolved_incidents} | đang mở: {report.open_incidents}",
    ]
    for item in report.monitors:
        lines.append(
            f"• {item.name}: uptime {_percent(item.uptime_percent)}, "
            f"{item.total_checks} lượt, phản hồi {_ms(item.avg_response_ms)}"
        )
    if not report.monitors:
        lines.append("Chưa có monitor nào gắn với tài khoản này.")
    if len(lines) == 5:
        lines.append("Chưa có dữ liệu kiểm tra trong khoảng thời gian này.")
    text = "\n".join(lines)
    return text if len(text) <= 4096 else text[:4070] + "\n… danh sách đã được rút gọn"


def _percent(value: float | None) -> str:
    return "chưa có dữ liệu" if value is None else f"{value:.2f}%"


def _ms(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f} ms"


def report_window(kind: str, now: datetime, zone: ZoneInfo) -> tuple[datetime, datetime, str, str]:
    """Return the previous complete day/week in local time, as UTC bounds."""
    local_now = now.astimezone(zone)
    today = local_now.date()
    if kind == "daily":
        period_day = today - timedelta(days=1)
        local_start = datetime.combine(period_day, time.min, tzinfo=zone)
        local_end = datetime.combine(today, time.min, tzinfo=zone)
        return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc), period_day.isoformat(), f"ngày {period_day:%d/%m/%Y}"
    if kind == "weekly":
        monday = today - timedelta(days=today.weekday())
        previous_monday = monday - timedelta(days=7)
        local_start = datetime.combine(previous_monday, time.min, tzinfo=zone)
        local_end = datetime.combine(monday, time.min, tzinfo=zone)
        return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc), previous_monday.strftime("%G-W%V"), f"tuần {previous_monday:%d/%m}–{(monday - timedelta(days=1)):%d/%m/%Y}"
    raise ValueError("Loại báo cáo phải là daily hoặc weekly")


async def send_due_reports(
    session_factory,
    telegram,
    settings: Settings,
    now: datetime | None = None,
) -> int:
    """Send scheduled reports once per user and completed reporting period."""
    settings.validate()
    zone = settings.report_zone
    local_now = (now or datetime.now(timezone.utc)).astimezone(zone)
    due: list[str] = []
    if local_now.hour >= settings.daily_report_hour:
        due.append("daily")
    if (
        local_now.weekday() > settings.weekly_report_weekday
        or (
            local_now.weekday() == settings.weekly_report_weekday
            and local_now.hour >= settings.weekly_report_hour
        )
    ):
        due.append("weekly")
    if not due:
        return 0

    sent = 0
    async with session_factory() as session:
        user_ids = (
            await session.scalars(
                select(distinct(NotificationChannel.user_id)).where(
                    NotificationChannel.type == "telegram"
                )
            )
        ).all()
        for user_id in user_ids:
            targets = (
                await session.scalars(
                    select(NotificationChannel.target).where(
                        NotificationChannel.user_id == user_id,
                        NotificationChannel.type == "telegram",
                    )
                )
            ).all()
            for kind in due:
                start, end, period_key, title = report_window(kind, local_now, zone)
                already_sent = await session.scalar(
                    select(ReportDelivery.id).where(
                        ReportDelivery.user_id == user_id,
                        ReportDelivery.report_type == kind,
                        ReportDelivery.period_key == period_key,
                    )
                )
                if already_sent is not None:
                    continue
                report = await collect_user_report(session, user_id, start, end)
                body = format_report(report, title, zone)
                try:
                    for target in dict.fromkeys(targets):
                        await telegram.send_message(target, body)
                except Exception as exc:
                    print(f"[telegram-bot] Không gửi được báo cáo {kind} cho user #{user_id}: {exc}")
                    continue
                session.add(
                    ReportDelivery(
                        user_id=user_id,
                        report_type=kind,
                        period_key=period_key,
                        sent_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()
                sent += 1
    return sent
