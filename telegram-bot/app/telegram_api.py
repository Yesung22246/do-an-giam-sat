"""Small async client for the Telegram Bot API."""
from __future__ import annotations

import httpx


class TelegramApiError(RuntimeError):
    pass


class TelegramApi:
    def __init__(self, token: str, base_url: str = "https://api.telegram.org") -> None:
        self.token = token.strip()
        self.base_url = base_url.rstrip("/")

    def _url(self, method: str) -> str:
        if not self.token:
            raise TelegramApiError("TELEGRAM_BOT_TOKEN chưa được cấu hình")
        return f"{self.base_url}/bot{self.token}/{method}"

    async def _call(self, method: str, payload: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(self._url(method), json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # HTTP exception strings can include the bot token in the request URL.
            raise TelegramApiError(f"Telegram API {method} request failed") from exc
        if not data.get("ok"):
            raise TelegramApiError(f"Telegram API {method} trả về lỗi")
        return data

    async def send_message(self, chat_id: str, text: str) -> None:
        await self._call("sendMessage", {"chat_id": chat_id, "text": text[:4096]})

    async def set_webhook(self, url: str, secret: str) -> None:
        payload = {"url": url}
        if secret:
            payload["secret_token"] = secret
        await self._call("setWebhook", payload)
