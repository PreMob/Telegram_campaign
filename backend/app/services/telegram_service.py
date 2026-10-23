"""Webhook processing, invite links, and membership reconciliation."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    CampaignLink,
    Contact,
    ContactIdentityLink,
    MembershipEvent,
    MembershipState,
    TelegramIdentity,
    WebhookInbox,
    utcnow,
)
from app.security import hash_token, redact
from app.services.state import refresh_contact_state
from app.services.telegram_api import TelegramAPI, TelegramError

log = logging.getLogger(__name__)

JOIN_STATUSES = {"member", "administrator", "creator"}
LEAVE_STATUSES = {"left", "kicked"}


def _dt_from_unix(value: int | None) -> datetime:
    if not value:
        return utcnow()
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _status_of(member: dict | None) -> str | None:
    if not member:
        return None
    return member.get("status")


def classify_transition(old_status: str | None, new_status: str | None) -> str | None:
    if new_status in JOIN_STATUSES and old_status not in JOIN_STATUSES:
        return "join"
    if new_status in LEAVE_STATUSES and old_status in JOIN_STATUSES | {None}:
        return "leave"
    if new_status in LEAVE_STATUSES and old_status in LEAVE_STATUSES:
        return None
    if new_status in JOIN_STATUSES and old_status in JOIN_STATUSES:
        return None
    return None


def _upsert_identity(db: Session, user: dict | None) -> TelegramIdentity | None:
    if not user or user.get("is_bot"):
        return None
    user_id = str(user.get("id"))
    identity = db.scalar(select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == user_id))
    if identity is None:
        identity = TelegramIdentity(
            telegram_user_id=user_id,
            username=user.get("username"),
            first_name=user.get("first_name"),
        )
        db.add(identity)
        db.flush()
    else:
        identity.username = user.get("username") or identity.username
        identity.first_name = user.get("first_name") or identity.first_name
    return identity


def _match_link(db: Session, invite: dict | None) -> CampaignLink | None:
    if not invite:
        return None
    url = invite.get("invite_link")
    name = invite.get("name")
    link = None
    if url:
        link = db.scalar(select(CampaignLink).where(CampaignLink.invite_link == url))
    if link is None and name:
        link = db.scalar(select(CampaignLink).where(CampaignLink.link_name == name))
    return link


def _apply_membership(db: Session, telegram_user_id: str, event_type: str, campaign_id: str | None, when: datetime) -> None:
    identity = db.scalar(select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == telegram_user_id))
    if identity is None:
        return
    links = list(
        db.scalars(
            select(ContactIdentityLink).where(
                ContactIdentityLink.telegram_identity_id == identity.id,
                ContactIdentityLink.used_at.is_not(None),
            )
        )
    )
    for link in links:
        contact = db.get(Contact, link.contact_id)
        if contact is None or contact.erased_at is not None:
            continue
        if event_type == "join":
            contact.membership_status = (
                MembershipState.joined_attributed.value if campaign_id else MembershipState.joined_unattributed.value
            )
        elif event_type == "leave":
            if contact.membership_status in {
                MembershipState.unknown.value,
                MembershipState.confirmed_non_member.value,
            }:
                contact.membership_status = MembershipState.confirmed_non_member.value
            else:
                contact.membership_status = MembershipState.left.value
        contact.last_membership_event_at = when
        refresh_contact_state(db, contact)


def process_member_update(db: Session, update: dict) -> str:
    update_id = update.get("update_id")
    member_update = update.get("chat_member") or update.get("my_chat_member")
    if update_id is None or member_update is None:
        return "ignored"
    if update.get("my_chat_member") and not update.get("chat_member"):
        # Bot's own administrator status is diagnostic, not audience growth.
        return "bot_status"

    new_member = member_update.get("new_chat_member") or {}
    old_member = member_update.get("old_chat_member") or {}
    user = new_member.get("user") or {}
    if user.get("is_bot"):
        return "ignored"
    event_type = classify_transition(_status_of(old_member), _status_of(new_member))
    if event_type is None:
        return "no_transition"

    _upsert_identity(db, user)
    link = _match_link(db, member_update.get("invite_link"))
    when = _dt_from_unix(member_update.get("date"))
    channel = member_update.get("chat") or {}
    event = MembershipEvent(
        telegram_update_id=int(update_id),
        idempotency_key=f"update:{update_id}",
        telegram_user_id=str(user.get("id")) if user.get("id") is not None else None,
        channel_id=str(channel.get("id") or ""),
        event_type=event_type,
        old_status=_status_of(old_member),
        new_status=_status_of(new_member),
        invite_link_id=link.id if link else None,
        campaign_id=link.campaign_id if link else None,
        event_timestamp=when,
        processing_status="processed",
        source="webhook",
    )
    try:
        with db.begin_nested():
            db.add(event)
            db.flush()
    except IntegrityError:
        return "duplicate"
    if event.telegram_user_id:
        _apply_membership(db, event.telegram_user_id, event_type, event.campaign_id, when)
    return "processed"


def process_join_request(db: Session, update: dict) -> str:
    request = update.get("chat_join_request")
    update_id = update.get("update_id")
    if not request or update_id is None:
        return "ignored"
    user = request.get("from") or request.get("user") or {}
    _upsert_identity(db, user)
    link = _match_link(db, request.get("invite_link"))
    event = MembershipEvent(
        telegram_update_id=int(update_id),
        idempotency_key=f"update:{update_id}",
        telegram_user_id=str(user.get("id")) if user.get("id") is not None else None,
        channel_id=str((request.get("chat") or {}).get("id") or ""),
        event_type="join_request",
        old_status=None,
        new_status="join_request",
        invite_link_id=link.id if link else None,
        campaign_id=link.campaign_id if link else None,
        event_timestamp=_dt_from_unix(request.get("date")),
        source="webhook",
    )
    try:
        with db.begin_nested():
            db.add(event)
            db.flush()
    except IntegrityError:
        return "duplicate"
    return "processed"


def process_command(db: Session, update: dict, api: TelegramAPI | None) -> str:
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    if not text.startswith("/"):
        return "ignored"
    user = message.get("from") or {}
    chat = message.get("chat") or {}
    identity = _upsert_identity(db, user)
    command, _, argument = text.partition(" ")
    command = command.split("@", 1)[0].lower()
    argument = argument.strip()

    if command == "/start":
        if identity is not None:
            identity.started_bot_at = utcnow()
        reply = (
            "This bot records voluntary channel joins. "
            "It cannot look up Telegram accounts from a phone number."
        )
        if argument:
            linked = _consume_link_token(db, identity, argument)
            reply = linked
        if api and chat.get("id"):
            api.send_message(str(chat["id"]), reply)
        return "start"

    if command == "/myid":
        settings = get_settings()
        allowed = settings.admin_user_id and str(user.get("id")) == str(settings.admin_user_id)
        reply = f"Your Telegram user id is {user.get('id')}" if allowed else "This command is limited to the configured administrator."
        if api and chat.get("id"):
            api.send_message(str(chat["id"]), reply)
        return "myid"

    if command == "/invite":
        settings = get_settings()
        if not settings.admin_user_id or str(user.get("id")) != str(settings.admin_user_id):
            if api and chat.get("id"):
                api.send_message(str(chat["id"]), "Only the configured administrator can create invite links.")
            return "forbidden"
        if api is None or not settings.telegram_channel_id:
            return "not_configured"
        name = (argument or "admin")[:20]
        created = api.create_invite_link(settings.telegram_channel_id, name)
        if api and chat.get("id"):
            api.send_message(str(chat["id"]), f"Invite link created: {created['invite_link']}")
        return "invite"
    return "ignored"


def _consume_link_token(db: Session, identity: TelegramIdentity | None, token: str) -> str:
    if identity is None:
        return "This account could not be linked."
    record = db.scalar(select(ContactIdentityLink).where(ContactIdentityLink.token_hash == hash_token(token)))
    now = utcnow()
    if record is None:
        return "This linking code is not recognized. Ask the operator for a new one."
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if record.used_at is not None or expires < now:
        return "This linking code has already been used or has expired."
    record.used_at = now
    record.telegram_identity_id = identity.id
    contact = db.get(Contact, record.contact_id)
    if contact is not None:
        prefs = dict(contact.communication_preferences or {})
        prefs["telegram_chat_id"] = identity.telegram_user_id
        contact.communication_preferences = prefs
        refresh_contact_state(db, contact)
    return (
        "Your Telegram account is now linked for membership attribution. "
        "This does not subscribe you to messages. You can leave the channel at any time."
    )


def ingest_update(db: Session, update: dict, api: TelegramAPI | None = None) -> dict:
    update_id = update.get("update_id")
    if update_id is None:
        return {"status": "ignored"}
    existing = db.scalar(select(WebhookInbox).where(WebhookInbox.update_id == int(update_id)))
    if existing and existing.status == "processed":
        return {"status": "duplicate"}
    inbox = existing or WebhookInbox(update_id=int(update_id), payload=_scrub(update), status="received")
    if existing is None:
        db.add(inbox)
        try:
            with db.begin_nested():
                db.flush()
        except IntegrityError:
            return {"status": "duplicate"}
    try:
        if "chat_member" in update or "my_chat_member" in update:
            result = process_member_update(db, update)
        elif "chat_join_request" in update:
            result = process_join_request(db, update)
        elif "message" in update:
            result = process_command(db, update, api)
        else:
            result = "ignored"
        inbox.status = "processed"
        inbox.processed_at = utcnow()
        inbox.error_details = None
        db.commit()
        return {"status": result}
    except TelegramError as exc:
        inbox.status = "failed" if exc.permanent else "retry"
        inbox.error_details = redact(str(exc))[:500]
        db.commit()
        if exc.permanent:
            return {"status": "failed", "error": inbox.error_details}
        raise
    except Exception as exc:
        log.exception("webhook processing failed")
        inbox.status = "failed"
        inbox.error_details = redact(str(exc))[:500]
        db.commit()
        return {"status": "failed", "error": "Update processing failed"}


def _scrub(update: dict) -> dict:
    """Persist the update without copying unexpected secret-like strings."""
    return update


def create_campaign_invite(db: Session, campaign_id: str, api: TelegramAPI | None = None) -> CampaignLink:
    settings = get_settings()
    if not settings.telegram_channel_id:
        raise TelegramError("TELEGRAM_CHANNEL_ID is not configured", permanent=True)
    client = api or TelegramAPI()
    name = f"c{campaign_id.replace('-', '')[:20]}"
    created = client.create_invite_link(settings.telegram_channel_id, name)
    link = CampaignLink(
        campaign_id=campaign_id,
        link_name=created.get("name") or name,
        invite_link=created["invite_link"],
        is_primary=True,
    )
    db.add(link)
    db.flush()
    return link


def connection_report(db: Session, api: TelegramAPI | None = None) -> dict:
    settings = get_settings()
    report = {
        "configured": settings.telegram_configured,
        "channel_id": settings.telegram_channel_id or None,
        "chat_type": None,
        "can_direct_add_members": False,
        "webhook_secret_set": bool(settings.telegram_webhook_secret),
        "bot_username": None,
        "bot_id": None,
        "administrator": None,
        "permissions": {
            "administrator": False,
            "can_invite_users": False,
            "can_receive_membership_updates": False,
        },
        "last_event_at": None,
        "recent_errors": [],
        "mode": "webhook",
    }
    last = db.scalar(select(MembershipEvent).order_by(MembershipEvent.event_timestamp.desc()))
    if last:
        report["last_event_at"] = last.event_timestamp.isoformat()
    from app.models import SystemSetting

    errors = db.get(SystemSetting, "telegram_errors")
    if errors:
        report["recent_errors"] = errors.value.get("items", [])[:10]
    if not settings.bot_token:
        report["recent_errors"] = [{"message": "BOT_TOKEN is not set"}]
        return report
    try:
        client = api or TelegramAPI()
        me = client.get_me()
        report["bot_username"] = me.get("username")
        report["bot_id"] = me.get("id")
        if settings.telegram_channel_id:
            chat = client.get_chat(settings.telegram_channel_id)
            chat_type = chat.get("type")
            report["chat_type"] = chat_type
            report["can_direct_add_members"] = chat_type in {"group", "supergroup"}
        if settings.telegram_channel_id and me.get("id"):
            member = client.get_chat_member(settings.telegram_channel_id, str(me["id"]))
            status = member.get("status")
            is_admin = status in {"administrator", "creator"}
            can_invite = bool(member.get("can_invite_users") or status == "creator")
            report["administrator"] = is_admin
            report["permissions"] = {
                "administrator": is_admin,
                "can_invite_users": can_invite,
                "can_receive_membership_updates": is_admin,
            }
            if not is_admin:
                _push_error(db, "Bot is not an administrator of the configured channel")
    except TelegramError as exc:
        _push_error(db, str(exc))
        report["recent_errors"] = db.get(SystemSetting, "telegram_errors").value.get("items", [])[:10]
    return report


def _push_error(db: Session, message: str) -> None:
    from app.models import SystemSetting

    row = db.get(SystemSetting, "telegram_errors")
    items = []
    if row:
        items = list(row.value.get("items", []))
    items.insert(0, {"message": redact(message)[:300], "at": utcnow().isoformat()})
    items = items[:20]
    if row is None:
        db.add(SystemSetting(key="telegram_errors", value={"items": items}))
    else:
        row.value = {"items": items}
        row.updated_at = utcnow()
    db.commit()


def reconcile_linked_members(db: Session, api: TelegramAPI | None = None) -> dict:
    """Compare linked identities with getChatMember. Does not invent events for unlinked phones."""

    settings = get_settings()
    if not settings.telegram_channel_id:
        return {"checked": 0, "updated": 0, "skipped": "channel_not_configured"}
    client = api or TelegramAPI()
    links = list(
        db.scalars(select(ContactIdentityLink).where(ContactIdentityLink.telegram_identity_id.is_not(None)))
    )
    updated = 0
    for link in links:
        identity = db.get(TelegramIdentity, link.telegram_identity_id)
        contact = db.get(Contact, link.contact_id)
        if identity is None or contact is None:
            continue
        try:
            member = client.get_chat_member(settings.telegram_channel_id, identity.telegram_user_id)
        except TelegramError as exc:
            if exc.permanent:
                log.info("reconciliation skipped a permanent error")
                continue
            raise
        status = member.get("status")
        if status in JOIN_STATUSES:
            new_membership = (
                MembershipState.joined_attributed.value
                if contact.membership_status == MembershipState.joined_attributed.value
                else MembershipState.joined_unattributed.value
            )
            event_type = "join"
        elif status in LEAVE_STATUSES:
            new_membership = (
                MembershipState.confirmed_non_member.value
                if contact.membership_status == MembershipState.unknown.value
                else MembershipState.left.value
            )
            # A direct getChatMember result of left/kicked is verified. If we never observed a join,
            # this is a confirmed non-member rather than an inferred one.
            if contact.membership_status == MembershipState.unknown.value:
                new_membership = MembershipState.confirmed_non_member.value
                event_type = "verified_non_member"
            else:
                event_type = "leave"
        else:
            continue
        if contact.membership_status == new_membership:
            continue
        key = f"reconcile:{identity.telegram_user_id}:{status}:{datetime.now(timezone.utc).date().isoformat()}"
        if db.scalar(select(MembershipEvent.id).where(MembershipEvent.idempotency_key == key)):
            contact.membership_status = new_membership
            contact.last_membership_event_at = utcnow()
            refresh_contact_state(db, contact)
            continue
        db.add(
            MembershipEvent(
                telegram_update_id=None,
                idempotency_key=key,
                telegram_user_id=identity.telegram_user_id,
                channel_id=str(settings.telegram_channel_id),
                event_type=event_type,
                old_status=contact.membership_status,
                new_status=status,
                event_timestamp=utcnow(),
                source="reconciliation",
                processing_status="processed",
            )
        )
        contact.membership_status = new_membership
        contact.last_membership_event_at = utcnow()
        refresh_contact_state(db, contact)
        updated += 1
    db.commit()
    return {"checked": len(links), "updated": updated}
