"""Điểm chạy chính của Monitoring Core.

Cách chạy:
    python -m app.main

Dừng bằng Ctrl+C.
"""
from __future__ import annotations

import asyncio
import signal
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from .config import settings
from .database import init_db
from .notifier import build_notifier
from .scheduler import MonitorScheduler
from .seed import seed_if_empty


async def main() -> None:
    # Khi ghép chung với Backend API (TV2), đặt AUTO_CREATE_TABLES=false để TV2
    # làm chủ việc tạo bảng; monitoring-core chỉ ghi dữ liệu vào bảng có sẵn.
    if settings.auto_create_tables:
        await init_db()
    if settings.seed_sample_monitors:
        await seed_if_empty()

    notifier = build_notifier(settings.alert_webhook_url or None)
    scheduler = MonitorScheduler(
        notifier=notifier, max_concurrent=settings.max_concurrent_checks
    )

    loop = asyncio.get_running_loop()
    # Bắt Ctrl+C để dừng êm (Windows có thể không hỗ trợ add_signal_handler).
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, scheduler.stop)
    except NotImplementedError:
        pass

    try:
        await scheduler.run_forever()
    except asyncio.CancelledError:
        pass
    print("[main] Đã dừng.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
