"""Kiểm tra website / API qua HTTP(S)."""
from __future__ import annotations

import time

import httpx

from ..models import Monitor
from .base import CheckOutcome


async def check_http(monitor: Monitor) -> CheckOutcome:
    """Gửi 1 request GET, đo thời gian phản hồi và kiểm tra mã trạng thái.

    Quy tắc "sống":
    - Nếu monitor.expected_status được đặt: mã phải khớp đúng.
    - Nếu không: mọi mã < 400 đều coi là sống.
    """
    url = monitor.target
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=monitor.timeout_seconds, follow_redirects=True
        ) as client:
            resp = await client.get(url)
        elapsed_ms = (time.perf_counter() - start) * 1000

        if monitor.expected_status is not None:
            ok = resp.status_code == monitor.expected_status
        else:
            ok = resp.status_code < 400

        if ok:
            return CheckOutcome.up(
                response_time_ms=round(elapsed_ms, 1), status_code=resp.status_code
            )
        return CheckOutcome.down(
            error=f"Mã trạng thái không mong đợi: {resp.status_code}",
            response_time_ms=round(elapsed_ms, 1),
            status_code=resp.status_code,
        )
    except httpx.TimeoutException:
        return CheckOutcome.down(error=f"Quá thời gian chờ ({monitor.timeout_seconds}s)")
    except httpx.ConnectError as exc:
        return CheckOutcome.down(error=f"Không kết nối được: {exc}")
    except httpx.HTTPError as exc:
        return CheckOutcome.down(error=f"Lỗi HTTP: {exc}")
