from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.bot_models import BotBase
from app.config import Settings
from app.main import create_app
from app.reporting import send_due_reports
from app.shared_models import (
    CheckResult,
    CheckRollup,
    Incident,
    Monitor,
    NotificationChannel,
    SharedBase,
    User,
)


class FakeTelegram:
    def __init__(self):
        self.messages: list[tuple[str, str]] = []
        self.webhooks: list[tuple[str, str]] = []

    async def send_message(self, chat_id: str, text: str) -> None:
        self.messages.append((chat_id, text))

    async def set_webhook(self, url: str, secret: str) -> None:
        self.webhooks.append((url, secret))


@asynccontextmanager
async def app_client(tmp_path: Path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'tv5-test.db'}"
    schema_engine = create_async_engine(url)
    async with schema_engine.begin() as connection:
        await connection.run_sync(SharedBase.metadata.create_all)
        await connection.run_sync(BotBase.metadata.create_all)
    await schema_engine.dispose()

    config = Settings(
        database_url=url,
        telegram_bot_token="test-token",
        telegram_webhook_url="",
        telegram_webhook_secret="test-webhook-secret",
        link_api_key="internal-test-key",
        link_code_ttl_seconds=600,
        report_timezone="Asia/Ho_Chi_Minh",
        daily_report_hour=8,
        weekly_report_day="mon",
        weekly_report_hour=8,
        report_poll_seconds=3600,
        auto_create_bot_tables=True,
    )
    fake = FakeTelegram()
    app = create_app(config, telegram_client=fake)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield app, client, fake


async def add_user_monitor(
    app,
    *,
    user_id: int = 7,
    monitor_id: int = 101,
    chat_id: str | None = "9001",
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(timezone.utc)
    async with app.state.database.sessions() as session:
        session.add(User(id=user_id))
        session.add(Monitor(id=monitor_id, owner_id=user_id, name="Shop API", enabled=True))
        if chat_id is not None:
            session.add(
                NotificationChannel(user_id=user_id, type="telegram", target=chat_id)
            )
        session.add_all(
            [
                CheckResult(
                    monitor_id=monitor_id,
                    checked_at=now - timedelta(minutes=10),
                    status="up",
                    response_time_ms=120.0,
                ),
                CheckResult(
                    monitor_id=monitor_id,
                    checked_at=now - timedelta(minutes=5),
                    status="down",
                    response_time_ms=None,
                ),
            ]
        )
        session.add(
            Incident(
                monitor_id=monitor_id,
                state="open",
                started_at=now - timedelta(minutes=4),
                resolved_at=None,
                severity="critical",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_tv1_alert_contract_routes_to_owner_and_formats_event(tmp_path):
    async with app_client(tmp_path) as (app, client, telegram):
        await add_user_monitor(app)
        response = await client.post(
            "/alerts",
            json={
                "monitor_id": 101,
                "monitor_name": "Shop API",
                "kind": "down",
                "severity": "critical",
                "message": "Dịch vụ SẬP. Nguyên nhân: Connection refused",
                "at": "2026-10-20T01:03:00+00:00",
                "response_time_ms": None,
                "status_code": None,
                "ssl_days_left": None,
            },
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True, "recipients": 1, "sent": 1, "failed": 0}
        assert telegram.messages[0][0] == "9001"
        assert "DỊCH VỤ SẬP" in telegram.messages[0][1]
        assert "Connection refused" in telegram.messages[0][1]


@pytest.mark.asyncio
async def test_secure_one_time_link_then_status_command(tmp_path):
    async with app_client(tmp_path) as (app, client, telegram):
        await add_user_monitor(app, chat_id=None)
        denied = await client.post("/link-codes", json={"user_id": 7})
        assert denied.status_code == 401

        issued = await client.post(
            "/link-codes",
            headers={"X-Internal-API-Key": "internal-test-key"},
            json={"user_id": 7},
        )
        assert issued.status_code == 200
        code = issued.json()["code"]
        linked = await client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret"},
            json={"message": {"chat": {"id": 9001}, "text": f"/start {code}"}},
        )
        assert linked.status_code == 200
        assert "Đã liên kết" in telegram.messages[-1][1]

        status = await client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret"},
            json={"message": {"chat": {"id": 9001}, "text": "/status 24"}},
        )
        assert status.status_code == 200
        assert "Shop API" in telegram.messages[-1][1]
        assert "Uptime: 50.00%" in telegram.messages[-1][1]
        assert "120.0 ms" in telegram.messages[-1][1]

        reused = await client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret"},
            json={"message": {"chat": {"id": 9002}, "text": f"/start {code}"}},
        )
        assert reused.status_code == 200
        assert "không hợp lệ" in telegram.messages[-1][1]


@pytest.mark.asyncio
async def test_webhook_secret_and_payload_validation(tmp_path):
    async with app_client(tmp_path) as (_, client, telegram):
        denied = await client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
            json={"message": {"chat": {"id": 4}, "text": "/help"}},
        )
        assert denied.status_code == 401
        invalid_alert = await client.post("/alerts", json={"monitor_id": -1})
        assert invalid_alert.status_code == 422
        assert telegram.messages == []


@pytest.mark.asyncio
async def test_scheduled_daily_and_weekly_reports_are_aggregated_and_deduplicated(tmp_path):
    async with app_client(tmp_path) as (app, _, telegram):
        zone = ZoneInfo("Asia/Ho_Chi_Minh")
        now = datetime(2026, 10, 19, 8, 5, tzinfo=zone)
        day_check = datetime(2026, 10, 18, 10, 0, tzinfo=zone)
        async with app.state.database.sessions() as session:
            session.add(User(id=7))
            session.add(Monitor(id=101, owner_id=7, name="Shop API", enabled=True))
            session.add(NotificationChannel(user_id=7, type="telegram", target="9001"))
            session.add_all(
                [
                    CheckResult(monitor_id=101, checked_at=day_check, status="up", response_time_ms=100),
                    CheckResult(monitor_id=101, checked_at=day_check + timedelta(minutes=5), status="up", response_time_ms=300),
                    CheckResult(monitor_id=101, checked_at=day_check + timedelta(minutes=10), status="down"),
                    Incident(monitor_id=101, state="resolved", started_at=day_check, resolved_at=day_check + timedelta(minutes=20), severity="critical"),
                ]
            )
            session.add(
                CheckRollup(
                    monitor_id=101,
                    bucket_start=datetime(2026, 10, 13, 0, 0, tzinfo=zone),
                    total_checks=10,
                    up_checks=9,
                    down_checks=1,
                    uptime_percent=90.0,
                    avg_response_ms=200.0,
                )
            )
            await session.commit()

        count = await send_due_reports(
            app.state.database.sessions, telegram, app.state.settings, now=now
        )
        assert count == 2
        assert len(telegram.messages) == 2
        bodies = [message for _, message in telegram.messages]
        assert any("Báo cáo ngày" in body and "66.67%" in body for body in bodies)
        assert any("Báo cáo tuần" in body and "84.62%" in body and "đã phục hồi: 1" in body for body in bodies)

        duplicate_count = await send_due_reports(
            app.state.database.sessions, telegram, app.state.settings, now=now
        )
        assert duplicate_count == 0
        assert len(telegram.messages) == 2
