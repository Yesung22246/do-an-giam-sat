"""Khởi tạo engine + session async."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import settings
from .models import Base

engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Tạo bảng nếu chưa có (đủ dùng cho đồ án; production nên dùng Alembic)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
