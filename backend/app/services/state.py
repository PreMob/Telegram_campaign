"""Derived contact state. Membership unknown is never treated as a confirmed non-join."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Consent,
    ConsentState,
    Contact,
    Invitation,
    InvitationStatus,
    LifecycleState,
    MembershipState,
    SuppressionRecord,
)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def effective_consent_status(rows: list[Consent], now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if not rows:
        return ConsentState.pending.value
    if any(row.status == ConsentState.withdrawn.value for row in rows):
        # A later granted consent is a new record. Withdrawal of a specific row does not
        # erase a newer grant for the same channel and purpose. Callers pass the relevant rows.
        pass
    latest_by_key: dict[tuple[str, str], Consent] = {}
    for row in rows:
        key = (row.channel, row.purpose)
        current = latest_by_key.get(key)
        if current is None or _aware(row.created_at) >= _aware(current.created_at):
            latest_by_key[key] = row
    statuses = []
    for row in latest_by_key.values():
        status = row.status
        expires = _aware(row.expires_at)
        if status == ConsentState.granted.value and expires and expires <= now:
            status = ConsentState.expired.value
        statuses.append(status)
    if any(status == ConsentState.granted.value for status in statuses):
        return ConsentState.granted.value
    if any(status == ConsentState.withdrawn.value for status in statuses):
        return ConsentState.withdrawn.value
    if any(status == ConsentState.expired.value for status in statuses):
        return ConsentState.expired.value
    return ConsentState.pending.value


def has_channel_consent(rows: list[Consent], channel: str, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    relevant = [row for row in rows if row.channel == channel]
    if not relevant:
        return False
    latest: Consent | None = None
    for row in relevant:
        if latest is None or _aware(row.created_at) >= _aware(latest.created_at):
            latest = row
    if latest is None or latest.status != ConsentState.granted.value:
        return False
    if latest.withdrawn_at is not None:
        return False
    expires = _aware(latest.expires_at)
    if expires and expires <= now:
        return False
    return True


def refresh_contact_state(db: Session, contact: Contact) -> Contact:
    db.flush()
    if contact.erased_at is not None:
        contact.lifecycle_status = LifecycleState.unknown.value
        contact.suppression_status = True
        return contact

    consents = list(db.scalars(select(Consent).where(Consent.contact_id == contact.id)))
    contact.consent_status = effective_consent_status(consents)
    active_suppression = db.scalar(
        select(SuppressionRecord.id).where(
            SuppressionRecord.contact_id == contact.id,
            SuppressionRecord.active.is_(True),
        )
    )
    contact.suppression_status = active_suppression is not None

    if contact.suppression_status:
        contact.lifecycle_status = LifecycleState.suppressed.value
        return contact

    membership = contact.membership_status
    if membership == MembershipState.joined_attributed.value:
        contact.lifecycle_status = LifecycleState.joined_attributed.value
        return contact
    if membership == MembershipState.joined_unattributed.value:
        contact.lifecycle_status = LifecycleState.joined_unattributed.value
        return contact
    if membership == MembershipState.left.value:
        contact.lifecycle_status = LifecycleState.left_channel.value
        return contact
    if membership == MembershipState.confirmed_non_member.value:
        contact.lifecycle_status = LifecycleState.not_joined_confirmed.value
        return contact

    latest = db.scalar(
        select(Invitation).where(Invitation.contact_id == contact.id).order_by(Invitation.created_at.desc())
    )
    if latest is not None:
        mapping = {
            InvitationStatus.queued.value: LifecycleState.invite_queued.value,
            InvitationStatus.attempted.value: LifecycleState.invite_attempted.value,
            InvitationStatus.accepted_by_provider.value: LifecycleState.invite_sent.value,
            InvitationStatus.delivery_confirmed.value: LifecycleState.delivery_confirmed.value,
            InvitationStatus.failed.value: LifecycleState.failed.value,
            InvitationStatus.cancelled.value: LifecycleState.eligible.value,
            InvitationStatus.suppressed.value: LifecycleState.suppressed.value,
        }
        if latest.status in mapping and latest.status != InvitationStatus.cancelled.value:
            contact.lifecycle_status = mapping[latest.status]
            return contact

    if contact.consent_status == ConsentState.granted.value:
        contact.lifecycle_status = LifecycleState.eligible.value
    elif contact.consent_status == ConsentState.pending.value:
        contact.lifecycle_status = LifecycleState.consent_pending.value
    else:
        contact.lifecycle_status = LifecycleState.consent_pending.value
    return contact
