"""Thêm vài monitor mẫu để chạy thử (khi DB còn trống)."""
from __future__ import annotations

from sqlalchemy import func, select

from .database import SessionLocal
from .models import Monitor, MonitorType


SAMPLES = [
    dict(name="Google", type=MonitorType.HTTP, target="https://www.google.com",
         interval_seconds=30, retries=3),
    dict(name="GitHub API", type=MonitorType.HTTP, target="https://api.github.com",
         interval_seconds=30, expected_status=200, retries=3),
    dict(name="Example SSL", type=MonitorType.SSL, target="example.com", port=443,
         interval_seconds=3600, ssl_warn_days=30),
    dict(name="Cloudflare DNS (TCP 53)", type=MonitorType.TCP, target="1.1.1.1",
         port=53, interval_seconds=30),
]


async def seed_if_empty() -> None:
    async with SessionLocal() as session:
        count = await session.scalar(select(func.count(Monitor.id))) or 0
        if count > 0:
            return
        for data in SAMPLES:
            session.add(Monitor(**data))
        await session.commit()
        print(f"[seed] Đã thêm {len(SAMPLES)} monitor mẫu.")
