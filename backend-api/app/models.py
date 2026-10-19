"""Schema Database chuẩn hợp nhất giữa TV2 (Backend API) và TV1 (Monitoring Core).

Bao gồm đầy đủ 8 bảng:
1. plans                  (TV2 quản lý gói dịch vụ)
2. users                  (TV2 quản lý tài khoản & phân quyền)
3. monitors               (TV2 CRUD, TV1 đọc để kiểm tra)
4. check_results          (TV1 ghi kết quả kiểm tra, TV2 đọc vẽ biểu đồ)
5. incidents              (TV1 ghi lịch sử sự cố, TV2 đọc)
6. check_rollups          (TV1 gom dữ liệu theo giờ)
7. monitor_alert_states   (TV1 lưu trạng thái cảnh báo chống spam)
8. notification_channels  (TV2 lưu cấu hình nhận tin, TV5 đọc gửi Telegram)
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional, List

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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ==================== ENUMS (KHỚP 100% VỚI TV1) ====================
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


# ==================== BẢNG CỦA TV2 (PLANS, USERS, CHANNELS) ====================
class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    max_monitors: Mapped[int] = mapped_column(Integer, nullable=False)
    min_interval: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    users: Mapped[List["User"]] = relationship("User", back_populates="plan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="customer")  # "admin" | "customer"
    plan_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, default=1
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    plan: Mapped[Optional["Plan"]] = relationship("Plan", back_populates="users", lazy="selectin")
    monitors: Mapped[List["Monitor"]] = relationship(
        "Monitor", back_populates="owner", cascade="all, delete-orphan"
    )
    notification_channels: Mapped[List["NotificationChannel"]] = relationship(
        "NotificationChannel", back_populates="user", cascade="all, delete-orphan"
    )


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(Text, nullable=False, default="telegram")
    target: Mapped[str] = mapped_column(Text, nullable=False)  # telegram chat_id

    user: Mapped["User"] = relationship("User", back_populates="notification_channels")


# ==================== BẢNG DÙNG CHUNG VỚI TV1 ====================
class Monitor(Base):
    __tablename__ = "monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Cho phép nullable=True để nếu TV1 chạy script seed demo không có owner_id vẫn không bị lỗi
    owner_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
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

    owner: Mapped[Optional["User"]] = relationship("User", back_populates="monitors")
    results: Mapped[list["CheckResult"]] = relationship(
        back_populates="monitor", cascade="all, delete-orphan"
    )
    incidents: Mapped[list["Incident"]] = relationship(
        back_populates="monitor", cascade="all, delete-orphan"
    )
    rollups: Mapped[list["CheckRollup"]] = relationship(
        back_populates="monitor", cascade="all, delete-orphan"
    )
    alert_state: Mapped[Optional["MonitorAlertState"]] = relationship(
        back_populates="monitor", uselist=False, cascade="all, delete-orphan"
    )


class CheckResult(Base):
    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), index=True
    )
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), index=True
    )
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


class CheckRollup(Base):
    __tablename__ = "check_rollups"
    __table_args__ = (
        UniqueConstraint("monitor_id", "bucket_start", name="uq_rollup_monitor_hour"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), index=True
    )
    bucket_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    total_checks: Mapped[int] = mapped_column(Integer, default=0)
    up_checks: Mapped[int] = mapped_column(Integer, default=0)
    down_checks: Mapped[int] = mapped_column(Integer, default=0)
    uptime_percent: Mapped[float] = mapped_column(Float, default=100.0)
    avg_response_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_response_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_response_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    monitor: Mapped["Monitor"] = relationship(back_populates="rollups")


class MonitorAlertState(Base):
    __tablename__ = "monitor_alert_states"

    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), primary_key=True
    )
    confirmed: Mapped[CheckStatus] = mapped_column(
        Enum(CheckStatus), default=CheckStatus.UP
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_successes: Mapped[int] = mapped_column(Integer, default=0)
    transitions: Mapped[list] = mapped_column(JSON, default=list)
    flapping_active: Mapped[bool] = mapped_column(Boolean, default=False)
    ssl_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    monitor: Mapped["Monitor"] = relationship(back_populates="alert_state")
