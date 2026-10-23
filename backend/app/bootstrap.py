"""Roles, first administrator, and clearly labeled demo records."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Campaign,
    CampaignStatus,
    Consent,
    ConsentState,
    Contact,
    MembershipEvent,
    Role,
    SuppressionRecord,
    User,
    utcnow,
)
from app.security import encrypt_phone, hash_password, phone_hmac
from app.services.state import refresh_contact_state

ROLES = {
    "super_admin": "Full administration, user management, and exports",
    "campaign_manager": "Contacts, campaigns, and Telegram operations",
    "analyst": "Read-only analytics with masked phone numbers",
    "read_only": "Read-only access with masked phone numbers",
}


def seed_roles(db: Session) -> None:
    existing = {role.name: role for role in db.scalars(select(Role))}
    for name, description in ROLES.items():
        if name not in existing:
            db.add(Role(name=name, description=description))
    db.flush()


def seed_admin(db: Session, email: str, password: str, full_name: str = "Administrator") -> None:
    if not email or not password:
        return
    seed_roles(db)
    if db.scalar(select(User).where(User.email == email.lower())):
        return
    role = db.scalar(select(Role).where(Role.name == "super_admin"))
    db.add(
        User(
            email=email.lower(),
            password_hash=hash_password(password),
            full_name=full_name,
            role_id=role.id,
            is_active=True,
        )
    )


def seed_demo(db: Session, actor_id: str | None = None) -> None:
    if db.scalar(select(Campaign).where(Campaign.name == "Demo: spring invite")):
        return
    samples = [
        ("+14155550101", "Demo Alex", "granted", False, "unknown"),
        ("+14155550102", "Demo Blair", "granted", False, "joined_attributed"),
        ("+14155550103", "Demo Casey", "pending", False, "unknown"),
        ("+14155550104", "Demo Devon", "granted", True, "unknown"),
        ("+14155550105", "Demo Ellis", "withdrawn", True, "unknown"),
        ("+14155550106", "Demo Fran", "granted", False, "confirmed_non_member"),
    ]
    now = datetime.now(timezone.utc)
    campaign = Campaign(
        name="Demo: spring invite",
        description="Sample campaign. These records are fake and marked as demo data.",
        objective="Show attributed joins without contacting anyone",
        target_audience={"membership": "any"},
        outreach_channel="telegram_invite",
        message_template="Hello {{name}}. You can join here: {{invite_link}}",
        status=CampaignStatus.running.value,
        created_by=actor_id,
        frequency_cap_days=7,
        actual_cost_cents=2500,
        is_demo=True,
        dispatch_lock=secrets.token_hex(8),
    )
    db.add(campaign)
    db.flush()
    for index, (phone, name, consent, suppressed, membership) in enumerate(samples):
        contact = Contact(
            phone_ciphertext=encrypt_phone(phone),
            phone_hmac=phone_hmac(phone),
            phone_last4=phone[-4:],
            name=name,
            source="demo_seed",
            consent_status=consent if consent != "withdrawn" else "withdrawn",
            membership_status=membership,
            is_demo=True,
            created_at=now - timedelta(days=10 - index),
        )
        db.add(contact)
        db.flush()
        if consent == "granted":
            db.add(
                Consent(
                    contact_id=contact.id,
                    channel="telegram_invite",
                    purpose="channel_invitation",
                    status=ConsentState.granted.value,
                    source="demo_seed",
                    policy_version="demo-1",
                )
            )
        elif consent == "withdrawn":
            db.add(
                Consent(
                    contact_id=contact.id,
                    channel="telegram_invite",
                    purpose="channel_invitation",
                    status=ConsentState.withdrawn.value,
                    source="demo_seed",
                    policy_version="demo-1",
                    withdrawn_at=utcnow(),
                )
            )
        if suppressed:
            db.add(SuppressionRecord(contact_id=contact.id, reason="demo_seed", source="demo_seed", active=True))
        refresh_contact_state(db, contact)
    db.add(
        MembershipEvent(
            telegram_update_id=900001,
            idempotency_key="demo:join:1",
            telegram_user_id="900001",
            channel_id="demo",
            event_type="join",
            old_status="left",
            new_status="member",
            campaign_id=campaign.id,
            event_timestamp=now - timedelta(days=2),
            source="demo_seed",
        )
    )
    db.add(
        MembershipEvent(
            telegram_update_id=900002,
            idempotency_key="demo:join:2",
            telegram_user_id="900002",
            channel_id="demo",
            event_type="join",
            old_status="left",
            new_status="member",
            campaign_id=None,
            event_timestamp=now - timedelta(days=1),
            source="demo_seed",
        )
    )
    db.add(
        MembershipEvent(
            telegram_update_id=900003,
            idempotency_key="demo:leave:1",
            telegram_user_id="900003",
            channel_id="demo",
            event_type="leave",
            old_status="member",
            new_status="left",
            event_timestamp=now - timedelta(hours=12),
            source="demo_seed",
        )
    )
