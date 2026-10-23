"""Campaign lifecycle. Delivery is separate from configuration and never assumes a phone is a Telegram user."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.models import (
    Campaign,
    CampaignAudience,
    CampaignEvent,
    CampaignStatus,
    Contact,
    Invitation,
    InvitationStatus,
    ProviderMessage,
    utcnow,
)
from app.services.eligibility import audience_preview, evaluate_contact
from app.services.providers import (
    PermanentProviderError,
    ProviderNotConfigured,
    TransientProviderError,
    get_provider,
)
from app.services.state import refresh_contact_state

PLACEHOLDERS = {"name", "invite_link"}
TEMPLATE_RE = re.compile(r"\{\{(\w+)\}\}")


class CampaignError(Exception):
    def __init__(self, message: str, status_code: int = 400, code: str = "campaign_error"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def validate_template(template: str) -> None:
    unknown = set(TEMPLATE_RE.findall(template or "")) - PLACEHOLDERS
    if unknown:
        raise CampaignError(f"Unsupported template placeholders: {', '.join(sorted(unknown))}")
    if "{{phone}}" in (template or "") or "{phone}" in (template or ""):
        raise CampaignError("Phone numbers cannot be inserted into message templates")


def render_message(template: str, contact: Contact, invite_link: str | None) -> str:
    return (template or "").replace("{{name}}", contact.name or "there").replace("{{invite_link}}", invite_link or "")


def add_event(db: Session, campaign: Campaign, actor_id: str | None, event_type: str, details: dict | None = None) -> None:
    db.add(CampaignEvent(campaign_id=campaign.id, actor_id=actor_id, event_type=event_type, details=details or {}))


def record_preview(db: Session, campaign: Campaign, actor_id: str | None) -> dict:
    summary = audience_preview(db, campaign)
    snapshot = {key: value for key, value in summary.items() if key != "eligible_ids"}
    db.add(
        CampaignAudience(
            campaign_id=campaign.id,
            eligible_count=summary["eligible"],
            excluded_count=summary["excluded"],
            suppressed_count=summary["suppressed"],
            unknown_consent_count=summary["unknown_consent"],
            unknown_membership_count=summary["unknown_membership"],
            joined_excluded_count=summary["joined_excluded"],
            rules_snapshot=snapshot,
            created_by=actor_id,
        )
    )
    return summary


def _ensure_window(campaign: Campaign, now: datetime) -> None:
    if campaign.end_at:
        end = campaign.end_at
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if end < now:
            raise CampaignError("Campaign end date has passed", 409, "campaign_ended")


def approve_campaign(db: Session, campaign: Campaign, actor) -> Campaign:
    if campaign.status != CampaignStatus.pending_approval.value:
        raise CampaignError("Only campaigns pending approval can be approved", 409, "invalid_status")
    if actor.role.name != "super_admin" and campaign.created_by == actor.id:
        raise CampaignError("A different operator must approve this campaign", 403, "separation_of_duties")
    campaign.status = CampaignStatus.approved.value
    campaign.approved_by = actor.id
    campaign.approved_at = utcnow()
    campaign.updated_at = utcnow()
    add_event(db, campaign, actor.id, "approved", {})
    write_audit(db, action="campaign.approve", entity_type="campaign", entity_id=campaign.id, actor_id=actor.id)
    return campaign


def launch_campaign(db: Session, campaign: Campaign, actor, *, confirm: bool, dry_run: bool) -> dict:
    if campaign.status not in {CampaignStatus.approved.value, CampaignStatus.scheduled.value}:
        raise CampaignError("Campaign must be approved before launch", 409, "invalid_status")
    if not dry_run and not confirm:
        raise CampaignError("Explicit confirmation is required before launch", 400, "confirmation_required")
    now = datetime.now(timezone.utc)
    _ensure_window(campaign, now)
    summary = record_preview(db, campaign, actor.id)
    if dry_run:
        campaign.dry_run = True
        add_event(db, campaign, actor.id, "dry_run", {"eligible": summary["eligible"]})
        write_audit(db, action="campaign.dry_run", entity_type="campaign", entity_id=campaign.id, actor_id=actor.id)
        db.commit()
        return {"dry_run": True, "status": campaign.status, "audience": _public_summary(summary)}

    if campaign.dispatch_lock:
        raise CampaignError("A launch job already exists for this campaign", 409, "duplicate_job")

    provider = get_provider(campaign.outreach_channel)
    invite_only = campaign.outreach_channel == "telegram_invite"
    if not provider.configured():
        if invite_only:
            raise CampaignError(
                "Telegram bot token and channel id are required.",
                422,
                "telegram_not_configured",
            )
        raise CampaignError(
            f"{campaign.outreach_channel} is not configured.",
            422,
            "provider_not_configured",
        )

    lock = str(uuid.uuid4())
    campaign.dispatch_lock = lock
    campaign.updated_at = utcnow()
    start = campaign.start_at
    if start and start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    deferred = bool(start and start > now)
    campaign.status = CampaignStatus.scheduled.value if deferred else CampaignStatus.running.value
    add_event(db, campaign, actor.id, "launch_confirmed", {"deferred": deferred, "eligible": summary["eligible"]})
    write_audit(db, action="campaign.launch", entity_type="campaign", entity_id=campaign.id, actor_id=actor.id)

    if invite_only:
        add_event(
            db,
            campaign,
            actor.id,
            "invite_link_skipped",
            {"note": "Invite links are not created automatically on launch."},
        )
        campaign.status = CampaignStatus.completed.value if not deferred else CampaignStatus.scheduled.value
        db.commit()
        return {
            "dry_run": False,
            "status": campaign.status,
            "invite_link": None,
            "audience": _public_summary(summary),
            "messages_queued": 0,
        }

    queued = 0
    for contact_id in summary["eligible_ids"]:
        key = f"{campaign.id}:{contact_id}"
        if db.scalar(select(Invitation.id).where(Invitation.idempotency_key == key)):
            continue
        db.add(
            Invitation(
                campaign_id=campaign.id,
                contact_id=contact_id,
                channel=campaign.outreach_channel,
                provider=provider.name,
                status=InvitationStatus.queued.value,
                idempotency_key=key,
            )
        )
        queued += 1
    db.commit()
    if not deferred:
        from app.services.jobs import enqueue_dispatch

        enqueue_dispatch(campaign.id)
    return {
        "dry_run": False,
        "status": campaign.status,
        "audience": _public_summary(summary),
        "messages_queued": queued,
    }


def _public_summary(summary: dict) -> dict:
    return {key: value for key, value in summary.items() if key != "eligible_ids"}


def dispatch_campaign(db: Session, campaign_id: str) -> dict:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        return {"status": "missing"}
    if campaign.status == CampaignStatus.scheduled.value:
        start = campaign.start_at
        now = datetime.now(timezone.utc)
        if start and (start if start.tzinfo else start.replace(tzinfo=timezone.utc)) > now:
            return {"status": "waiting"}
        campaign.status = CampaignStatus.running.value
        db.commit()
    if campaign.status != CampaignStatus.running.value:
        return {"status": campaign.status}

    provider = get_provider(campaign.outreach_channel)
    link = None
    from app.models import CampaignLink

    primary = db.scalar(
        select(CampaignLink).where(CampaignLink.campaign_id == campaign.id, CampaignLink.revoked.is_(False))
    )
    if primary:
        link = primary.invite_link
    invitations = list(
        db.scalars(
            select(Invitation).where(
                Invitation.campaign_id == campaign.id,
                Invitation.status == InvitationStatus.queued.value,
            )
        )
    )
    sent = 0
    for invitation in invitations:
        db.refresh(campaign)
        if campaign.status == CampaignStatus.paused.value:
            db.commit()
            return {"status": "paused", "processed": sent}
        if campaign.status == CampaignStatus.cancelled.value:
            invitation.status = InvitationStatus.cancelled.value
            continue
        contact = db.get(Contact, invitation.contact_id) if invitation.contact_id else None
        if contact is None:
            invitation.status = InvitationStatus.failed.value
            invitation.error = "contact_missing"
            continue
        target = (campaign.target_audience or {}).get("membership", "any")
        source = (campaign.target_audience or {}).get("source")
        ok, reason = evaluate_contact(
            db,
            contact,
            outreach_channel=campaign.outreach_channel,
            target_membership=target,
            frequency_cap_days=campaign.frequency_cap_days or 0,
            source=source,
        )
        if not ok:
            invitation.status = (
                InvitationStatus.suppressed.value if reason == "suppressed" else InvitationStatus.cancelled.value
            )
            invitation.error = reason
            refresh_contact_state(db, contact)
            continue
        invitation.status = InvitationStatus.attempted.value
        db.commit()
        try:
            result = provider.send(contact, render_message(campaign.message_template, contact, link), link)
        except TransientProviderError:
            invitation.status = InvitationStatus.queued.value
            invitation.error = "transient_provider_error"
            db.commit()
            raise
        except (PermanentProviderError, ProviderNotConfigured) as exc:
            invitation.status = InvitationStatus.failed.value
            invitation.error = str(exc)[:300]
            refresh_contact_state(db, contact)
            db.commit()
            continue
        invitation.status = result.status
        invitation.error = None if result.delivered or result.status != InvitationStatus.failed.value else result.detail
        contact.last_permitted_outreach_at = utcnow()
        refresh_contact_state(db, contact)
        db.add(
            ProviderMessage(
                invitation_id=invitation.id,
                provider=provider.name,
                external_id=result.external_id,
                state=result.status,
                detail={"detail": result.detail, "delivered": result.delivered},
            )
        )
        sent += 1
        db.commit()

    db.refresh(campaign)
    remaining = db.scalar(
        select(Invitation.id).where(
            Invitation.campaign_id == campaign.id,
            Invitation.status == InvitationStatus.queued.value,
        )
    )
    if campaign.status == CampaignStatus.running.value and remaining is None:
        campaign.status = CampaignStatus.completed.value
        campaign.updated_at = utcnow()
        add_event(db, campaign, None, "completed", {"processed": sent})
    db.commit()
    return {"status": campaign.status, "processed": sent}


def pause_campaign(db: Session, campaign: Campaign, actor) -> Campaign:
    if campaign.status != CampaignStatus.running.value:
        raise CampaignError("Only a running campaign can be paused", 409, "invalid_status")
    campaign.status = CampaignStatus.paused.value
    campaign.updated_at = utcnow()
    add_event(db, campaign, actor.id, "paused", {})
    write_audit(db, action="campaign.pause", entity_type="campaign", entity_id=campaign.id, actor_id=actor.id)
    return campaign


def resume_campaign(db: Session, campaign: Campaign, actor) -> Campaign:
    if campaign.status != CampaignStatus.paused.value:
        raise CampaignError("Only a paused campaign can be resumed", 409, "invalid_status")
    campaign.status = CampaignStatus.running.value
    campaign.updated_at = utcnow()
    add_event(db, campaign, actor.id, "resumed", {})
    write_audit(db, action="campaign.resume", entity_type="campaign", entity_id=campaign.id, actor_id=actor.id)
    db.commit()
    from app.services.jobs import enqueue_dispatch

    enqueue_dispatch(campaign.id)
    return campaign


def cancel_campaign(db: Session, campaign: Campaign, actor) -> Campaign:
    if campaign.status in {CampaignStatus.completed.value, CampaignStatus.cancelled.value}:
        raise CampaignError("Campaign is already finished", 409, "invalid_status")
    campaign.status = CampaignStatus.cancelled.value
    campaign.updated_at = utcnow()
    queued = list(
        db.scalars(
            select(Invitation).where(
                Invitation.campaign_id == campaign.id,
                Invitation.status == InvitationStatus.queued.value,
            )
        )
    )
    for invitation in queued:
        invitation.status = InvitationStatus.cancelled.value
        if invitation.contact_id:
            contact = db.get(Contact, invitation.contact_id)
            if contact:
                refresh_contact_state(db, contact)
    add_event(db, campaign, actor.id, "cancelled", {"queued_cancelled": len(queued)})
    write_audit(db, action="campaign.cancel", entity_type="campaign", entity_id=campaign.id, actor_id=actor.id)
    return campaign


def duplicate_campaign(db: Session, campaign: Campaign, actor) -> Campaign:
    copy = Campaign(
        name=f"{campaign.name} copy",
        description=campaign.description,
        objective=campaign.objective,
        target_audience=dict(campaign.target_audience or {}),
        outreach_channel=campaign.outreach_channel,
        message_template=campaign.message_template,
        start_at=campaign.start_at,
        end_at=campaign.end_at,
        status=CampaignStatus.draft.value,
        created_by=actor.id,
        frequency_cap_days=campaign.frequency_cap_days,
        budget_cents=campaign.budget_cents,
        actual_cost_cents=campaign.actual_cost_cents,
    )
    db.add(copy)
    db.flush()
    add_event(db, copy, actor.id, "duplicated", {"source_campaign_id": campaign.id})
    return copy
