"""Read/write mappings for the shared TV2/monitoring-core schema.

The bot maps only columns it reads or updates. TV2 remains responsible for
creating and migrating these tables; this module never creates them at startup.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Float
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class SharedBase(DeclarativeBase):
    pass


class User(SharedBase):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class Monitor(SharedBase):
    __tablename__ = "monitors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class CheckResult(SharedBase):
    __tablename__ = "check_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id"), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20))
    response_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)


class CheckRollup(SharedBase):
    __tablename__ = "check_rollups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id"), index=True)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    total_checks: Mapped[int] = mapped_column(Integer)
    up_checks: Mapped[int] = mapped_column(Integer)
    down_checks: Mapped[int] = mapped_column(Integer)
    uptime_percent: Mapped[float] = mapped_column(Float)
    avg_response_ms: Mapped[float | None] = mapped_column(Float, nullable=True)


class Incident(SharedBase):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id"), index=True)
    state: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="critical")


class NotificationChannel(SharedBase):
    __tablename__ = "notification_channels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    target: Mapped[str] = mapped_column(String(255), index=True)
