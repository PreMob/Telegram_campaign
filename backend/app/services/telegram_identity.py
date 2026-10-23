"""Resolve a voluntary Telegram user id for a contact. Phone numbers are never looked up on Telegram."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contact, ContactIdentityLink, TelegramIdentity


def resolve_telegram_user_id(db: Session, contact: Contact) -> str | None:
    prefs = contact.communication_preferences or {}
    chat_id = prefs.get("telegram_chat_id") or prefs.get("telegram_user_id")
    if chat_id:
        return str(chat_id)
    link = db.scalar(
        select(ContactIdentityLink)
        .where(
            ContactIdentityLink.contact_id == contact.id,
            ContactIdentityLink.telegram_identity_id.is_not(None),
            ContactIdentityLink.used_at.is_not(None),
        )
        .order_by(ContactIdentityLink.used_at.desc())
    )
    if link is None:
        return None
    identity = db.get(TelegramIdentity, link.telegram_identity_id)
    if identity is None:
        return None
    return identity.telegram_user_id
