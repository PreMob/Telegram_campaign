"""Server-side eligibility. Existence in the contact table is not permission to message."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Consent, Contact, MembershipState, SuppressionRecord
from app.services.state import has_channel_consent, refresh_contact_state

JOINED = {MembershipState.joined_attributed.value, MembershipState.joined_unattributed.value}


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def channel_for_consent(outreach_channel: str) -> str:
    if outreach_channel in {"telegram_invite", "telegram_dm", "telegram_channel_add"}:
        return outreach_channel
    return outreach_channel


def evaluate_contact(
    db: Session,
    contact: Contact,
    *,
    outreach_channel: str,
    target_membership: str,
    frequency_cap_days: int,
    now: datetime | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    source: str | None = None,
    preloaded_consents: list | None = None,
    suppressed_ids: set[str] | None = None,
) -> tuple[bool, str]:
    """Return (eligible, reason). Reason is empty when the contact may be included."""

    now = now or datetime.now(timezone.utc)
    if contact.erased_at is not None:
        return False, "erased"
    if suppressed_ids is None:
        refresh_contact_state(db, contact)
        suppressed = contact.suppression_status
        consents = None
    else:
        suppressed = contact.id in suppressed_ids
        consents = preloaded_consents or []
    if source and contact.source != source:
        return False, "source_mismatch"
    if start_at and _aware(start_at) > now:
        return False, "campaign_not_started"
    if end_at and _aware(end_at) < now:
        return False, "campaign_ended"
    if suppressed:
        return False, "suppressed"

    if consents is None:
        consents = list(db.scalars(select(Consent).where(Consent.contact_id == contact.id)))
    consent_channel = channel_for_consent(outreach_channel)
    if not has_channel_consent(consents, consent_channel, now):
        return False, "consent_missing"

    if contact.membership_status in JOINED:
        return False, "already_joined"

    if target_membership == "confirmed_non_member":
        if contact.membership_status == MembershipState.unknown.value:
            return False, "unknown_membership"
        if contact.membership_status != MembershipState.confirmed_non_member.value:
            return False, "not_confirmed_non_member"
    elif target_membership == "unknown":
        if contact.membership_status != MembershipState.unknown.value:
            return False, "membership_not_unknown"

    if frequency_cap_days and contact.last_permitted_outreach_at:
        last = _aware(contact.last_permitted_outreach_at)
        if last + timedelta(days=frequency_cap_days) > now:
            return False, "frequency_cap"

    if outreach_channel == "telegram_channel_add":
        from app.services.telegram_identity import resolve_telegram_user_id

        if not resolve_telegram_user_id(db, contact):
            return False, "telegram_not_linked"

    return True, ""


def audience_preview(db: Session, campaign) -> dict:
    """Count eligibility for a campaign. Dates are enforced by launch, not by this preview."""

    from collections import defaultdict

    contacts = list(db.scalars(select(Contact).where(Contact.erased_at.is_(None))))
    consents_by: dict[str, list] = defaultdict(list)
    for row in db.scalars(select(Consent)):
        consents_by[row.contact_id].append(row)
    suppressed = set(
        db.scalars(select(SuppressionRecord.contact_id).where(SuppressionRecord.active.is_(True)))
    )
    target = (campaign.target_audience or {}).get("membership", "any")
    source = (campaign.target_audience or {}).get("source")
    counts = {
        "eligible": 0,
        "excluded": 0,
        "suppressed": 0,
        "unknown_consent": 0,
        "unknown_membership": 0,
        "joined_excluded": 0,
        "reasons": {},
    }
    eligible_ids: list[str] = []
    for contact in contacts:
        if contact.membership_status == MembershipState.unknown.value:
            counts["unknown_membership"] += 1
        ok, reason = evaluate_contact(
            db,
            contact,
            outreach_channel=campaign.outreach_channel,
            target_membership=target,
            frequency_cap_days=campaign.frequency_cap_days or 0,
            start_at=None,
            end_at=None,
            source=source,
            preloaded_consents=consents_by.get(contact.id, []),
            suppressed_ids=suppressed,
        )
        if reason == "suppressed":
            counts["suppressed"] += 1
        if reason == "consent_missing":
            counts["unknown_consent"] += 1
        if reason == "already_joined":
            counts["joined_excluded"] += 1
        if ok:
            counts["eligible"] += 1
            eligible_ids.append(contact.id)
        else:
            counts["excluded"] += 1
            counts["reasons"][reason] = counts["reasons"].get(reason, 0) + 1
    counts["eligible_ids"] = eligible_ids
    counts["scanned"] = len(contacts)
    return counts

