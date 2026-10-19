"""Kiểm tra hạn chứng chỉ SSL/TLS của một host.

Trả về DOWN nếu chứng chỉ đã hết hạn hoặc không lấy được.
Trả về UP kèm ssl_days_left nếu còn hạn (Alert Engine sẽ quyết định
có cảnh báo "sắp hết hạn" hay không dựa trên ngưỡng ssl_warn_days).
"""
from __future__ import annotations

import socket
import ssl
from datetime import datetime, timezone

import asyncio

from ..models import Monitor
from .base import CheckOutcome

_CERT_TIME_FMT = "%b %d %H:%M:%S %Y %Z"


def _fetch_cert_days_left(host: str, port: int, timeout: float) -> int:
    """Hàm đồng bộ (chạy trong thread): bắt tay TLS và đọc ngày hết hạn."""
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            cert = ssock.getpeercert()
    not_after = cert["notAfter"]
    expire = datetime.strptime(not_after, _CERT_TIME_FMT).replace(tzinfo=timezone.utc)
    delta = expire - datetime.now(timezone.utc)
    return delta.days


async def check_ssl(monitor: Monitor) -> CheckOutcome:
    host = monitor.target
    port = monitor.port or 443
    try:
        days_left = await asyncio.wait_for(
            asyncio.to_thread(
                _fetch_cert_days_left, host, port, monitor.timeout_seconds
            ),
            timeout=monitor.timeout_seconds + 2,
        )
    except asyncio.TimeoutError:
        return CheckOutcome.down(error="Quá thời gian chờ khi bắt tay TLS")
    except ssl.SSLCertVerificationError as exc:
        return CheckOutcome.down(error=f"Chứng chỉ không hợp lệ: {exc.verify_message}")
    except (ssl.SSLError, socket.gaierror, OSError) as exc:
        return CheckOutcome.down(error=f"Lỗi SSL/kết nối: {exc}")

    if days_left < 0:
        return CheckOutcome.down(
            error=f"Chứng chỉ đã hết hạn {abs(days_left)} ngày trước",
            ssl_days_left=days_left,
        )
    return CheckOutcome.up(ssl_days_left=days_left)
