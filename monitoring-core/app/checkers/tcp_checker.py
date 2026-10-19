"""Kiểm tra một cổng TCP có mở không (vd database, SSH, SMTP...)."""
from __future__ import annotations

import asyncio
import time

from ..models import Monitor
from .base import CheckOutcome


async def check_tcp(monitor: Monitor) -> CheckOutcome:
    """Thử mở kết nối TCP tới host:port. Mở được = sống."""
    host = monitor.target
    port = monitor.port
    if port is None:
        return CheckOutcome.down(error="Monitor TCP thiếu cổng (port)")

    start = time.perf_counter()
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout=monitor.timeout_seconds)
        elapsed_ms = (time.perf_counter() - start) * 1000
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return CheckOutcome.up(response_time_ms=round(elapsed_ms, 1))
    except asyncio.TimeoutError:
        return CheckOutcome.down(error=f"Quá thời gian chờ ({monitor.timeout_seconds}s)")
    except (ConnectionRefusedError, OSError) as exc:
        return CheckOutcome.down(error=f"Không mở được cổng {port}: {exc}")
