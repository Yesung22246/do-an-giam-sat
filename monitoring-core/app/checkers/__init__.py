"""Các bộ kiểm tra (checker) cho từng loại mục tiêu."""
from __future__ import annotations

from ..models import Monitor, MonitorType
from .base import CheckOutcome
from .http_checker import check_http
from .ssl_checker import check_ssl
from .tcp_checker import check_tcp


async def run_check(monitor: Monitor) -> CheckOutcome:
    """Chọn đúng checker theo loại monitor rồi chạy."""
    if monitor.type == MonitorType.HTTP:
        return await check_http(monitor)
    if monitor.type == MonitorType.TCP:
        return await check_tcp(monitor)
    if monitor.type == MonitorType.SSL:
        return await check_ssl(monitor)
    raise ValueError(f"Loại monitor không hỗ trợ: {monitor.type}")


__all__ = ["run_check", "CheckOutcome", "check_http", "check_tcp", "check_ssl"]
