"""TV5 Telegram service. Run with: uvicorn app.main:app --port 8080"""
from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from .bot_models import TelegramLinkCode
from .config import Settings
from .database import Database
from .reporting import collect_user_report, format_report, report_window, send_due_reports
from .shared_models import Monitor, NotificationChannel, User
from .telegram_api import TelegramApi, TelegramApiError


class AlertPayload(BaseModel):
    """Immutable webhook format shared with monitoring-core TV1."""
    monitor_id: int = Field(gt=0)
    monitor_name: str = Field(min_length=1, max_length=200)
    kind: Literal["down", "recovered", "flapping", "stabilized", "ssl_expiring"]
    severity: Literal["critical", "warning", "info"]
    message: str = Field(min_length=1, max_length=2000)
    at: datetime
    response_time_ms: float | None = None
    status_code: int | None = None
    ssl_days_left: int | None = None


class LinkCodeRequest(BaseModel):
    user_id: int = Field(gt=0)


class LinkCodeResponse(BaseModel):
    code: str
    expires_at: datetime


_SEVERITY_ICON = {"critical": "🔴", "warning": "🟡", "info": "🟢"}
_KIND_LABEL = {
    "down": "DỊCH VỤ SẬP",
    "recovered": "ĐÃ PHỤC HỒI",
    "flapping": "CHẬP CHỜN",
    "stabilized": "ĐÃ ỔN ĐỊNH",
    "ssl_expiring": "SSL SẮP HẾT HẠN",
}


def format_alert(event: AlertPayload, zone: ZoneInfo) -> str:
    at = event.at
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    lines = [
        f"{_SEVERITY_ICON[event.severity]} [{event.severity.upper()}] {_KIND_LABEL[event.kind]}",
        f"{event.monitor_name} (#{event.monitor_id})",
        event.message,
        f"Thời gian: {at.astimezone(zone):%d/%m/%Y %H:%M:%S %Z}",
    ]
    details = []
    if event.response_time_ms is not None:
        details.append(f"Phản hồi {event.response_time_ms:.1f} ms")
    if event.status_code is not None:
        details.append(f"HTTP {event.status_code}")
    if event.ssl_days_left is not None:
        details.append(f"SSL còn {event.ssl_days_left} ngày")
    if details:
        lines.append(" | ".join(details))
    return "\n".join(lines)


def _new_code() -> str:
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def create_app(
    settings: Settings | None = None,
    telegram_client: TelegramApi | None = None,
) -> FastAPI:
    config = settings or Settings()
    config.validate()
    db = Database(config.database_url)
    telegram = telegram_client or TelegramApi(
        config.telegram_bot_token, config.telegram_api_base_url
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.database = db
        app.state.settings = config
        app.state.telegram = telegram
        if config.auto_create_bot_tables:
            await db.create_bot_tables()
        if config.telegram_webhook_url:
            if not config.telegram_bot_token:
                raise RuntimeError("TELEGRAM_BOT_TOKEN is required when TELEGRAM_WEBHOOK_URL is set")
            await telegram.set_webhook(config.telegram_webhook_url, config.telegram_webhook_secret)
        report_task = asyncio.create_task(_report_loop(db, telegram, config))
        try:
            yield
        finally:
            report_task.cancel()
            await asyncio.gather(report_task, return_exceptions=True)
            await db.close()

    app = FastAPI(title="TV5 Telegram Bot", version="1.0.0", lifespan=lifespan)

    @app.get("/health")
    async def health(request: Request):
        try:
            await request.app.state.database.ping()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        return {
            "status": "ok",
            "telegram_configured": bool(config.telegram_bot_token),
            "webhook_configured": bool(config.telegram_webhook_url),
        }

    @app.post("/alerts")
    async def receive_alert(event: AlertPayload, request: Request):
        """Receive the locked TV1 JSON contract and notify the monitor owner."""
        session_factory = request.app.state.database.sessions
        async with session_factory() as session:
            owner_id = await session.scalar(
                select(Monitor.owner_id).where(Monitor.id == event.monitor_id)
            )
            if owner_id is None:
                return {"ok": True, "recipients": 0, "sent": 0, "failed": 0}
            targets = (
                await session.scalars(
                    select(NotificationChannel.target).where(
                        NotificationChannel.user_id == owner_id,
                        NotificationChannel.type == "telegram",
                    )
                )
            ).all()

        sent = failed = 0
        message = format_alert(event, config.report_zone)
        for target in dict.fromkeys(targets):
            try:
                await request.app.state.telegram.send_message(target, message)
                sent += 1
            except Exception as exc:
                failed += 1
                print(f"[telegram-bot] Gửi alert cho monitor #{event.monitor_id} thất bại: {exc}")
        return {"ok": failed == 0, "recipients": len(set(targets)), "sent": sent, "failed": failed}

    @app.post("/link-codes", response_model=LinkCodeResponse)
    async def create_link_code(
        body: LinkCodeRequest,
        request: Request,
        x_internal_api_key: str | None = Header(default=None),
    ):
        """Internal endpoint for TV2 to issue a one-time Telegram linking code."""
        if not config.link_api_key:
            raise HTTPException(status_code=503, detail="Telegram linking is not configured")
        if not x_internal_api_key or not secrets.compare_digest(
            x_internal_api_key, config.link_api_key
        ):
            raise HTTPException(status_code=401, detail="invalid internal API key")

        async with request.app.state.database.sessions() as session:
            exists = await session.scalar(select(User.id).where(User.id == body.user_id))
            if exists is None:
                raise HTTPException(status_code=404, detail="user not found")
            await session.execute(
                delete(TelegramLinkCode).where(
                    TelegramLinkCode.user_id == body.user_id,
                    TelegramLinkCode.consumed_at.is_(None),
                )
            )
            now = datetime.now(timezone.utc)
            code = _new_code()
            expires_at = now + timedelta(seconds=config.link_code_ttl_seconds)
            session.add(
                TelegramLinkCode(
                    code=code,
                    user_id=body.user_id,
                    created_at=now,
                    expires_at=expires_at,
                )
            )
            await session.commit()
        return LinkCodeResponse(code=code, expires_at=expires_at)

    @app.post("/telegram/webhook")
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ):
        expected = config.telegram_webhook_secret
        if expected and (
            not x_telegram_bot_api_secret_token
            or not secrets.compare_digest(x_telegram_bot_api_secret_token, expected)
        ):
            raise HTTPException(status_code=401, detail="invalid Telegram webhook secret")
        update = await request.json()
        message = update.get("message") if isinstance(update, dict) else None
        if not isinstance(message, dict):
            return {"ok": True}
        chat = message.get("chat") or {}
        text = message.get("text")
        if not chat.get("id") or not isinstance(text, str):
            return {"ok": True}
        await _handle_command(
            request.app.state.database,
            request.app.state.telegram,
            config,
            str(chat["id"]),
            text,
        )
        return {"ok": True}

    return app


async def _handle_command(db: Database, telegram, settings: Settings, chat_id: str, text: str) -> None:
    command_text = text.strip()
    if not command_text.startswith("/"):
        return
    parts = command_text.split(maxsplit=1)
    command = parts[0].split("@", 1)[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""
    answer: str

    if command == "/start":
        if not argument:
            answer = (
                "Chào bạn! Để liên kết tài khoản, hãy lấy mã tại trang tài khoản rồi gửi: "
                "/start <mã-liên-kết>. Mã chỉ dùng một lần và hết hạn sau 10 phút.\n"
                "Dùng /help để xem lệnh."
            )
        else:
            code = argument.split()[0].upper()
            now = datetime.now(timezone.utc)
            async with db.sessions() as session:
                link = await session.get(TelegramLinkCode, code)
                if link is None or link.consumed_at is not None or _utc(link.expires_at) <= now:
                    answer = "Mã liên kết không hợp lệ, đã dùng hoặc hết hạn. Hãy tạo mã mới trong trang tài khoản."
                else:
                    link.consumed_at = now
                    channel = await session.scalar(
                        select(NotificationChannel).where(
                            NotificationChannel.type == "telegram",
                            NotificationChannel.target == chat_id,
                        )
                    )
                    if channel is None:
                        session.add(NotificationChannel(user_id=link.user_id, type="telegram", target=chat_id))
                    else:
                        channel.user_id = link.user_id
                    await session.commit()
                    answer = "Đã liên kết Telegram với tài khoản. Bạn sẽ nhận cảnh báo và báo cáo định kỳ tại đây."
    elif command == "/help":
        answer = (
            "Lệnh Telegram:\n"
            "/status [giờ] — thống kê gần đây (mặc định 24 giờ)\n"
            "/report daily|weekly — báo cáo ngày/tuần đã hoàn tất\n"
            "/stop — ngừng nhận cảnh báo tại cuộc trò chuyện này"
        )
    elif command in {"/status", "/report"}:
        async with db.sessions() as session:
            user_id = await session.scalar(
                select(NotificationChannel.user_id).where(
                    NotificationChannel.type == "telegram",
                    NotificationChannel.target == chat_id,
                )
            )
            if user_id is None:
                answer = "Tài khoản chưa liên kết. Hãy lấy mã trong trang tài khoản và gửi /start <mã>."
            elif command == "/status":
                try:
                    hours = int(argument) if argument else 24
                    if not 1 <= hours <= 720:
                        raise ValueError
                except ValueError:
                    answer = "Số giờ phải là số nguyên từ 1 đến 720. Ví dụ: /status 24"
                else:
                    end = datetime.now(timezone.utc)
                    start = end - timedelta(hours=hours)
                    report = await collect_user_report(session, user_id, start, end)
                    answer = format_report(report, f"{hours} giờ gần nhất", settings.report_zone)
            else:
                kind = argument.lower() if argument else "daily"
                if kind not in {"daily", "weekly"}:
                    answer = "Cú pháp: /report daily hoặc /report weekly"
                else:
                    start, end, _, title = report_window(kind, datetime.now(timezone.utc), settings.report_zone)
                    report = await collect_user_report(session, user_id, start, end)
                    answer = format_report(report, title, settings.report_zone)
    elif command == "/stop":
        async with db.sessions() as session:
            result = await session.execute(
                delete(NotificationChannel).where(
                    NotificationChannel.type == "telegram",
                    NotificationChannel.target == chat_id,
                )
            )
            await session.commit()
            answer = "Đã ngừng nhận cảnh báo ở cuộc trò chuyện này." if result.rowcount else "Cuộc trò chuyện này chưa được liên kết."
    else:
        return

    try:
        await telegram.send_message(chat_id, answer)
    except TelegramApiError as exc:
        print(f"[telegram-bot] Gửi phản hồi lệnh {command} thất bại: {exc}")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


async def _report_loop(db: Database, telegram, settings: Settings) -> None:
    while True:
        try:
            count = await send_due_reports(db.sessions, telegram, settings)
            if count:
                print(f"[telegram-bot] Đã gửi {count} báo cáo định kỳ.")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[telegram-bot] Lỗi tạo báo cáo định kỳ: {exc}")
        await asyncio.sleep(settings.report_poll_seconds)


app = create_app()
