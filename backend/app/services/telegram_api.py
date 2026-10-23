"""Official Telegram Bot API wrapper. Invite URLs come from Telegram, never from string formatting."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from app.config import get_settings
from app.security import redact

log = logging.getLogger(__name__)


class TelegramError(Exception):
    def __init__(self, message: str, permanent: bool = False):
        super().__init__(redact(message))
        self.permanent = permanent


class TelegramClient(Protocol):
    def get_me(self) -> dict: ...

    def get_chat_member(self, chat_id: str, user_id: str) -> dict: ...

    def create_chat_invite_link(self, chat_id: str, name: str) -> dict: ...

    def send_message(self, chat_id: str, text: str) -> dict: ...

    def add_chat_member(self, chat_id: str, user_id: str) -> dict: ...

    def get_chat(self, chat_id: str) -> dict: ...


class PythonTelegramBotClient:
    """Uses python-telegram-bot's Bot for every network call."""

    def __init__(self, token: str):
        self.token = token

    def _run(self, factory):
        async def inner():
            from telegram import Bot
            from telegram.error import InvalidToken, NetworkError, RetryAfter
            from telegram.error import TelegramError as PTBError

            bot = Bot(self.token)
            try:
                return await factory(bot)
            except InvalidToken as exc:
                raise TelegramError("Telegram rejected the bot token", permanent=True) from exc
            except RetryAfter as exc:
                raise TelegramError("Telegram asked us to retry later", permanent=False) from exc
            except NetworkError as exc:
                raise TelegramError("Telegram network error", permanent=False) from exc
            except PTBError as exc:
                text = redact(str(exc))
                permanent = "not enough rights" in text.lower() or "chat not found" in text.lower() or "bot was kicked" in text.lower()
                raise TelegramError(text or "Telegram API error", permanent=permanent) from exc
            finally:
                await bot.shutdown()

        return asyncio.run(inner())

    def get_me(self) -> dict:
        me = self._run(lambda bot: bot.get_me())
        return {"id": me.id, "username": me.username, "is_bot": me.is_bot}

    def get_chat_member(self, chat_id: str, user_id: str) -> dict:
        member = self._run(lambda bot: bot.get_chat_member(chat_id=chat_id, user_id=int(user_id)))
        payload = {"status": member.status}
        user = getattr(member, "user", None)
        if user is not None:
            payload["user_id"] = str(user.id)
        for flag in ("can_invite_users", "can_restrict_members", "is_member"):
            if hasattr(member, flag):
                payload[flag] = getattr(member, flag)
        return payload

    def create_chat_invite_link(self, chat_id: str, name: str) -> dict:
        link = self._run(lambda bot: bot.create_chat_invite_link(chat_id=chat_id, name=name[:32]))
        if not link.invite_link:
            raise TelegramError("Telegram did not return an invite link", permanent=True)
        return {"invite_link": link.invite_link, "name": link.name or name}

    def send_message(self, chat_id: str, text: str) -> dict:
        message = self._run(lambda bot: bot.send_message(chat_id=int(chat_id), text=text[:4096]))
        return {"message_id": message.message_id}

    def get_chat(self, chat_id: str) -> dict:
        import httpx

        response = httpx.post(
            f"https://api.telegram.org/bot{self.token}/getChat",
            json={"chat_id": chat_id},
            timeout=20.0,
        )
        payload = response.json()
        if not payload.get("ok"):
            raise TelegramError(payload.get("description") or "getChat failed", permanent=True)
        return payload.get("result") or {}

    def add_chat_member(self, chat_id: str, user_id: str) -> dict:
        import httpx

        url = f"https://api.telegram.org/bot{self.token}/addChatMember"
        try:
            response = httpx.post(
                url,
                json={"chat_id": chat_id, "user_id": int(user_id)},
                timeout=30.0,
            )
        except httpx.TimeoutException as exc:
            raise TelegramError("Telegram network timeout", permanent=False) from exc
        payload = response.json()
        if not payload.get("ok"):
            description = (payload.get("description") or "addChatMember failed").lower()
            code = payload.get("error_code")
            if "user is already" in description or "already a member" in description or "already_participant" in description:
                return {"ok": True, "already_member": True}
            if code == 404 or "not found" in description:
                raise TelegramError(
                    "Telegram broadcast channels do not support addChatMember for subscribers. "
                    "Use a private bot invite to each person who has tapped Start on the bot, or switch to a supergroup.",
                    permanent=True,
                )
            permanent = any(
                part in description
                for part in (
                    "not enough rights",
                    "chat_admin_required",
                    "user_not_found",
                    "peer_id_invalid",
                    "method is not available",
                    "can't add",
                    "cannot add",
                )
            )
            raise TelegramError(payload.get("description") or "addChatMember failed", permanent=permanent)
        return {"ok": True, "already_member": False}


_client: TelegramClient | None = None


def get_telegram_client() -> TelegramClient:
    if _client is not None:
        return _client
    settings = get_settings()
    if not settings.bot_token:
        raise TelegramError("Bot token is not configured", permanent=True)
    return PythonTelegramBotClient(settings.bot_token)


def set_telegram_client(client: TelegramClient | None) -> None:
    global _client
    _client = client


class TelegramAPI:
    def __init__(self, client: TelegramClient | None = None):
        self.client = client or get_telegram_client()

    def get_me(self) -> dict:
        return self.client.get_me()

    def get_chat_member(self, chat_id: str, user_id: str) -> dict:
        return self.client.get_chat_member(chat_id, user_id)

    def create_invite_link(self, chat_id: str, name: str) -> dict:
        return self.client.create_chat_invite_link(chat_id, name)

    def send_message(self, chat_id: str, text: str) -> dict:
        return self.client.send_message(chat_id, text)

    def add_chat_member(self, chat_id: str, user_id: str) -> dict:
        return self.client.add_chat_member(chat_id, user_id)

    def get_chat(self, chat_id: str) -> dict:
        return self.client.get_chat(chat_id)
