"""Notifier — nơi phát sự kiện cảnh báo ra ngoài.

Đây chính là "ranh giới ghép việc" giữa TV1 và TV5:
- TV1 (bạn) sinh ra AlertEvent.
- TV5 (Telegram bot) nhận AlertEvent rồi gửi tin nhắn.

Hợp đồng dữ liệu giữa hai người là hàm event_to_dict() dưới đây.
TV5 chỉ cần dựng 1 endpoint HTTP nhận đúng JSON này là ghép được ngay.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from .alert_engine import AlertEvent


def event_to_dict(event: AlertEvent) -> dict:
    """Chuẩn hoá 1 sự kiện cảnh báo thành JSON — HỢP ĐỒNG với TV5."""
    o = event.outcome
    return {
        "monitor_id": event.monitor_id,
        "monitor_name": event.monitor_name,
        "kind": event.kind.value,          # down | recovered | flapping | stabilized | ssl_expiring
        "severity": event.severity,        # critical | warning | info
        "message": event.message,
        "at": event.at.isoformat(),
        "response_time_ms": o.response_time_ms if o else None,
        "status_code": o.status_code if o else None,
        "ssl_days_left": o.ssl_days_left if o else None,
    }


class Notifier(ABC):
    @abstractmethod
    async def send(self, event: AlertEvent) -> None: ...

    async def send_many(self, events: list[AlertEvent]) -> None:
        for event in events:
            await self.send(event)


class ConsoleNotifier(Notifier):
    """In cảnh báo ra màn hình — dùng khi TV1 tự test, chưa có Telegram."""

    _ICON = {
        "critical": "[!] SẬP   ",
        "warning": "[~] CẢNH  ",
        "info": "[+] OK    ",
    }

    async def send(self, event: AlertEvent) -> None:
        icon = self._ICON.get(event.severity, "[*]")
        ts = event.at.strftime("%H:%M:%S")
        print(f"{ts} {icon} #{event.monitor_id} {event.monitor_name}: {event.message}")


class WebhookNotifier(Notifier):
    """Đẩy cảnh báo tới endpoint HTTP của TV5 (Telegram bot)."""

    def __init__(self, url: str) -> None:
        self.url = url

    async def send(self, event: AlertEvent) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(self.url, json=event_to_dict(event))
        except httpx.HTTPError as exc:
            # Không để lỗi gửi cảnh báo làm chết vòng giám sát.
            print(f"[notifier] Gửi webhook thất bại: {exc}")


def build_notifier(webhook_url: str | None) -> Notifier:
    """Chọn notifier theo cấu hình: có webhook thì đẩy đi, không thì in console."""
    if webhook_url:
        return WebhookNotifier(webhook_url)
    return ConsoleNotifier()
