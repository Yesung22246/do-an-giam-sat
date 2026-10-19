"""Các bảng dữ liệu (SQLAlchemy).

Lưu ý ghép nhóm: đây là schema phần giám sát do TV1 sở hữu.
TV2 (Backend API) nên đồng bộ 3 bảng này trong "hợp đồng" database chung:
- monitors      : mục tiêu cần giám sát (do người dùng/TV2 thêm qua API)
- check_results : mỗi lần kiểm tra ghi 1 dòng (nguồn dữ liệu vẽ biểu đồ)
- incidents     : mỗi lần sự cố mở/đóng (nguồn dữ liệu "lịch sử sự cố")
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class MonitorType(str, enum.Enum):
    HTTP = "http"      # kiểm tra website/API qua HTTP(S)
    TCP = "tcp"        # kiểm tra cổng dịch vụ (vd: database, SSH)
    SSL = "ssl"        # kiểm tra hạn chứng chỉ SSL/TLS


class CheckStatus(str, enum.Enum):
    UP = "up"
    DOWN = "down"


class IncidentState(str, enum.Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class Monitor(Base):
    __tablename__ = "monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[MonitorType] = mapped_column(Enum(MonitorType))

    # Với HTTP: target là URL. Với TCP/SSL: target là host, kèm port.
    target: Mapped[str] = mapped_column(String(500))
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)

    interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=10.0)

    # HTTP: mã trạng thái coi là "sống" (vd 200). None = mọi mã < 400 đều OK.
    expected_status: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Số lần lỗi liên tiếp phải đạt mới coi là DOWN (chống báo nhầm do mạng chập).
    retries: Mapped[int] = mapped_column(Integer, default=3)

    # SSL: cảnh báo khi số ngày còn lại <= ngưỡng này.
    ssl_warn_days: Mapped[int] = mapped_column(Integer, default=14)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    results: Mapped[list["CheckResult"]] = relationship(
        back_populates="monitor", cascade="all, delete-orphan"
    )
    incidents: Mapped[list["Incident"]] = relationship(
        back_populates="monitor", cascade="all, delete-orphan"
    )


class CheckResult(Base):
    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id"))
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    status: Mapped[CheckStatus] = mapped_column(Enum(CheckStatus))
    response_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ssl_days_left: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    monitor: Mapped["Monitor"] = relationship(back_populates="results")


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id"))
    state: Mapped[IncidentState] = mapped_column(
        Enum(IncidentState), default=IncidentState.OPEN
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "critical" = sập hẳn, "warning" = sắp hết hạn SSL / chập chờn.
    severity: Mapped[str] = mapped_column(String(20), default="critical")

    monitor: Mapped["Monitor"] = relationship(back_populates="incidents")


class MonitorAlertState(Base):
    """Lưu lại trạng thái Alert Engine của mỗi monitor xuống DB.

    Nhờ bảng này, khi service khởi động lại (restart, crash, deploy mới) thì
    engine nạp lại đúng trạng thái cũ -> KHÔNG báo trùng "SẬP" cho dịch vụ đã
    biết là đang sập, không reset nhầm bộ đếm lỗi/flapping.

    Mỗi monitor đúng 1 dòng (monitor_id là khóa chính).
    """
    __tablename__ = "monitor_alert_states"

    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id"), primary_key=True
    )
    confirmed: Mapped[CheckStatus] = mapped_column(
        Enum(CheckStatus), default=CheckStatus.UP
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_successes: Mapped[int] = mapped_column(Integer, default=0)
    # Danh sách mốc đổi trạng thái gần đây (ISO string) để xét flapping.
    transitions: Mapped[list] = mapped_column(JSON, default=list)
    flapping_active: Mapped[bool] = mapped_column(Boolean, default=False)
    ssl_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
