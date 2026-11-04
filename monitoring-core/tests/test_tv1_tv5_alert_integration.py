"""Cross-service test of TV1 -> authenticated TV5 -> linked Telegram chat."""
from __future__ import annotations

import importlib
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.alert_engine import AlertEvent, AlertKind
from app.checkers.base import CheckOutcome
from app.notifier import WebhookNotifier


BOT_APP_DIR = Path(__file__).resolve().parents[2] / "telegram-bot" / "app"
BOT_PACKAGE = "telegram_bot_service"

if BOT_PACKAGE not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        BOT_PACKAGE,
        BOT_APP_DIR / "__init__.py",
        submodule_search_locations=[str(BOT_APP_DIR)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[BOT_PACKAGE] = package
    spec.loader.exec_module(package)

bot_models = importlib.import_module(f"{BOT_PACKAGE}.bot_models")
bot_config = importlib.import_module(f"{BOT_PACKAGE}.config")
bot_main = importlib.import_module(f"{BOT_PACKAGE}.main")
bot_shared = importlib.import_module(f"{BOT_PACKAGE}.shared_models")


class FakeTelegram:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def send_message(self, chat_id: str, text: str) -> None:
        self.messages.append((chat_id, text))

    async def set_webhook(self, url: str, secret: str) -> None:
        raise AssertionError("Webhook registration is not needed in this test")


@pytest.mark.asyncio
async def test_tv1_alert_reaches_linked_user_via_authenticated_tv5_endpoint(tmp_path):
    secret = "shared-system-test-secret-with-32-plus-chars"
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'full-system.db'}"
    schema_engine = create_async_engine(database_url)
    async with schema_engine.begin() as connection:
        await connection.run_sync(bot_shared.SharedBase.metadata.create_all)
        await connection.run_sync(bot_models.BotBase.metadata.create_all)
    await schema_engine.dispose()

    settings = bot_config.Settings(
        database_url=database_url,
        alert_webhook_secret=secret,
        telegram_bot_token="test-token",
        report_timezone="Asia/Ho_Chi_Minh",
        report_poll_seconds=3600,
    )
    telegram = FakeTelegram()
    app = bot_main.create_app(settings, telegram_client=telegram)

    async with app.router.lifespan_context(app):
        async with app.state.database.sessions() as session:
            session.add(bot_shared.User(id=55))
            session.add(
                bot_shared.Monitor(
                    id=301, owner_id=55, name="Demo Web", enabled=True
                )
            )
            session.add(
                bot_shared.NotificationChannel(
                    user_id=55, type="telegram", target="991122"
                )
            )
            await session.commit()

        transport = httpx.ASGITransport(app=app)

        def client_factory(**kwargs):
            return httpx.AsyncClient(
                transport=transport, base_url="http://telegram-bot", **kwargs
            )

        tv1 = WebhookNotifier(
            "http://telegram-bot/alerts", secret, client_factory=client_factory
        )
        event = AlertEvent(
            monitor_id=301,
            monitor_name="Demo Web",
            kind=AlertKind.DOWN,
            message="Dịch vụ SẬP. Nguyên nhân: kiểm thử tích hợp",
            at=datetime.now(timezone.utc),
            outcome=CheckOutcome.down("kiểm thử tích hợp"),
        )
        await tv1.send(event)

    assert len(telegram.messages) == 1
    assert telegram.messages[0][0] == "991122"
    assert "Demo Web" in telegram.messages[0][1]
    assert "kiểm thử tích hợp" in telegram.messages[0][1]
