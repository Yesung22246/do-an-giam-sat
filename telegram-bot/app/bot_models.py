"""Tables owned by TV5 for one-time account linking and report deduplication."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class BotBase(DeclarativeBase):
    pass


class TelegramLinkCode(BotBase):
    __tablename__ = "telegram_link_codes"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReportDelivery(BotBase):
    __tablename__ = "telegram_report_deliveries"
    __table_args__ = (
        UniqueConstraint("user_id", "report_type", "period_key", name="uq_telegram_report_period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    report_type: Mapped[str] = mapped_column(String(16))
    period_key: Mapped[str] = mapped_column(String(32))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
