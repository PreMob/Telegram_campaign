"""Outreach adapters. Unconfigured providers refuse to send and never report delivery."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.models import Contact, InvitationStatus


@dataclass
class ProviderResult:
    status: str
    detail: str
    external_id: str | None = None
    delivered: bool = False


class ProviderNotConfigured(Exception):
    def __init__(self, provider: str):
        super().__init__(f"{provider} is not configured")
        self.provider = provider


class PermanentProviderError(Exception):
    pass


class TransientProviderError(Exception):
    pass


class OutreachProvider:
    name = "base"

    def configured(self) -> bool:
        return False

    def send(self, contact: Contact, message: str, invite_link: str | None) -> ProviderResult:
        raise ProviderNotConfigured(self.name)


class TelegramInviteProvider(OutreachProvider):
    """Invite-link campaigns do not message the contact list."""

    name = "telegram_invite"

    def configured(self) -> bool:
        return get_settings().telegram_configured

    def send(self, contact: Contact, message: str, invite_link: str | None) -> ProviderResult:
        raise PermanentProviderError("Telegram invite campaigns publish a link; they do not message phone numbers")


class TelegramChannelAddProvider(OutreachProvider):
    """Uses addChatMember. Requires a linked Telegram user id; cannot add by phone number."""

    name = "telegram_channel_add"

    def configured(self) -> bool:
        return get_settings().telegram_configured

    def send(self, contact: Contact, message: str, invite_link: str | None) -> ProviderResult:
        from app.database import SessionLocal
        from app.services.telegram_api import TelegramAPI, TelegramError
        from app.services.telegram_identity import resolve_telegram_user_id

        settings = get_settings()
        db = SessionLocal()
        try:
            user_id = resolve_telegram_user_id(db, contact)
        finally:
            db.close()
        if not user_id:
            raise PermanentProviderError(
                "This contact is not linked to a Telegram account. Open the bot, tap Start, "
                "and use the identity link code from the contact profile."
            )
        client = TelegramAPI()
        try:
            result = client.add_chat_member(settings.telegram_channel_id, user_id)
        except TelegramError as exc:
            if exc.permanent:
                raise PermanentProviderError(str(exc)) from exc
            raise TransientProviderError(str(exc)) from exc
        detail = "Added to the channel via Telegram addChatMember."
        if result.get("already_member"):
            detail = "Telegram reports the user is already in the channel."
        return ProviderResult(
            status=InvitationStatus.accepted_by_provider.value,
            detail=detail,
            external_id=user_id,
            delivered=False,
        )


class TelegramDmProvider(OutreachProvider):
    name = "telegram_dm"

    def configured(self) -> bool:
        return bool(get_settings().bot_token)

    def send(self, contact: Contact, message: str, invite_link: str | None) -> ProviderResult:
        # The worker supplies a voluntary chat id through the contact preference stamp.
        chat_id = (contact.communication_preferences or {}).get("telegram_chat_id")
        if not chat_id:
            raise PermanentProviderError("Contact has not started the bot; Telegram DM is not permitted")
        from app.services.telegram_api import TelegramAPI

        TelegramAPI().send_message(str(chat_id), message)
        return ProviderResult(
            status=InvitationStatus.accepted_by_provider.value,
            detail="Telegram accepted sendMessage. Delivery is not confirmed by this response.",
            delivered=False,
        )


class EmailProvider(OutreachProvider):
    name = "email"

    def configured(self) -> bool:
        settings = get_settings()
        return bool(settings.smtp_host and settings.smtp_from)

    def send(self, contact: Contact, message: str, invite_link: str | None) -> ProviderResult:
        if not self.configured():
            raise ProviderNotConfigured(self.name)
        address = (contact.communication_preferences or {}).get("email")
        if not address:
            raise PermanentProviderError("Contact has no email address on file")
        # Acceptance by the local SMTP handshake is not delivery confirmation.
        import smtplib
        from email.message import EmailMessage

        settings = get_settings()
        email = EmailMessage()
        email["From"] = settings.smtp_from
        email["To"] = address
        email["Subject"] = "Channel update"
        email.set_content(message)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as client:
                client.starttls()
                if settings.smtp_username:
                    client.login(settings.smtp_username, settings.smtp_password)
                client.send_message(email)
        except (TimeoutError, OSError) as exc:
            raise TransientProviderError(str(exc)) from exc
        return ProviderResult(
            status=InvitationStatus.accepted_by_provider.value,
            detail="SMTP server accepted the message. This is not a delivery confirmation.",
            delivered=False,
        )


class HttpChannelProvider(OutreachProvider):
    def __init__(self, name: str, url: str, token: str):
        self.name = name
        self.url = url
        self.token = token

    def configured(self) -> bool:
        return bool(self.url and self.token)

    def send(self, contact: Contact, message: str, invite_link: str | None) -> ProviderResult:
        if not self.configured():
            raise ProviderNotConfigured(self.name)
        import httpx

        try:
            response = httpx.post(
                self.url,
                headers={"Authorization": f"Bearer {self.token}"},
                json={"message": message, "invite_link": invite_link, "contact_id": contact.id},
                timeout=20,
            )
        except httpx.TimeoutException as exc:
            raise TransientProviderError("provider timeout") from exc
        if response.status_code in {408, 429, 500, 502, 503, 504}:
            raise TransientProviderError(f"provider status {response.status_code}")
        if response.status_code >= 400:
            raise PermanentProviderError(f"provider rejected the message ({response.status_code})")
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        delivered = bool(body.get("delivered") is True)
        status = (
            InvitationStatus.delivery_confirmed.value
            if delivered
            else InvitationStatus.accepted_by_provider.value
        )
        return ProviderResult(status=status, detail="Provider HTTP response recorded", delivered=delivered, external_id=body.get("id"))


class FakeProvider(OutreachProvider):
    """Test double. Not registered in production."""

    name = "fake"

    def __init__(self, result: ProviderResult | None = None, error: Exception | None = None):
        self.result = result or ProviderResult(
            status=InvitationStatus.accepted_by_provider.value,
            detail="Test provider accepted the request",
            delivered=False,
        )
        self.error = error
        self.sent = 0

    def configured(self) -> bool:
        return True

    def send(self, contact: Contact, message: str, invite_link: str | None) -> ProviderResult:
        self.sent += 1
        if self.error:
            raise self.error
        return self.result


def get_provider(channel: str) -> OutreachProvider:
    settings = get_settings()
    if channel == "telegram_invite":
        return TelegramInviteProvider()
    if channel == "telegram_channel_add":
        return TelegramChannelAddProvider()
    if channel == "telegram_dm":
        return TelegramDmProvider()
    if channel == "email":
        return EmailProvider()
    if channel == "sms":
        return HttpChannelProvider("sms", settings.sms_api_url, settings.sms_api_token)
    if channel == "whatsapp":
        return HttpChannelProvider("whatsapp", settings.whatsapp_api_url, settings.whatsapp_api_token)
    raise PermanentProviderError(f"Unknown outreach channel {channel}")
