"""Database-backed metrics. Zero recorded events are not treated as a full membership census."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Campaign, Contact, Invitation, InvitationStatus, MembershipEvent

ATTEMPTED = {
    InvitationStatus.attempted.value,
    InvitationStatus.accepted_by_provider.value,
    InvitationStatus.delivery_confirmed.value,
    InvitationStatus.failed.value,
}
ACCEPTED = {InvitationStatus.accepted_by_provider.value, InvitationStatus.delivery_confirmed.value}


def _parse_dt(value: str | None, end: bool = False) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if len(value) == 10 and end:
        parsed = parsed + timedelta(days=1)
    return parsed


def metric(key: str, label: str, value, state: str, definition: dict, note: str | None = None) -> dict:
    return {
        "key": key,
        "label": label,
        "value": value,
        "value_state": state,
        "definition": definition,
        "note": note,
    }


def _contact_filters(stmt, source: str | None, consent: str | None, start, end):
    stmt = stmt.where(Contact.erased_at.is_(None))
    if source:
        stmt = stmt.where(Contact.source == source)
    if consent:
        stmt = stmt.where(Contact.consent_status == consent)
    if start:
        stmt = stmt.where(Contact.created_at >= start)
    if end:
        stmt = stmt.where(Contact.created_at < end)
    return stmt


def overview(db: Session, params: dict) -> dict:
    start = _parse_dt(params.get("from"))
    end = _parse_dt(params.get("to"), end=True)
    source = params.get("source")
    consent = params.get("consent_status")
    campaign_id = params.get("campaign_id")
    provider = params.get("provider")
    window = "all stored records" if not start and not end else f"{params.get('from') or 'start'} to {params.get('to') or 'now'}"

    def contacts(extra=None):
        stmt = select(func.count()).select_from(Contact)
        stmt = _contact_filters(stmt, source, consent, start, end)
        if extra is not None:
            stmt = stmt.where(extra)
        return int(db.scalar(stmt) or 0)

    total = contacts()
    pending = contacts(Contact.consent_status == "pending")
    suppressed = contacts(Contact.suppression_status.is_(True))
    eligible = contacts(Contact.lifecycle_status == "ELIGIBLE")

    def invitations(statuses: set[str] | None = None):
        stmt = select(func.count()).select_from(Invitation)
        if statuses:
            stmt = stmt.where(Invitation.status.in_(statuses))
        if campaign_id:
            stmt = stmt.where(Invitation.campaign_id == campaign_id)
        if provider:
            stmt = stmt.where(Invitation.provider == provider)
        if start:
            stmt = stmt.where(Invitation.created_at >= start)
        if end:
            stmt = stmt.where(Invitation.created_at < end)
        return int(db.scalar(stmt) or 0)

    attempted = invitations(ATTEMPTED)
    accepted = invitations(ACCEPTED)
    delivered = invitations({InvitationStatus.delivery_confirmed.value})
    failed = invitations({InvitationStatus.failed.value})

    def events(event_type: str, attributed: bool | None):
        stmt = select(func.count()).select_from(MembershipEvent).where(MembershipEvent.event_type == event_type)
        if attributed is True:
            stmt = stmt.where(MembershipEvent.campaign_id.is_not(None))
        elif attributed is False:
            stmt = stmt.where(MembershipEvent.campaign_id.is_(None))
        if campaign_id:
            stmt = stmt.where(MembershipEvent.campaign_id == campaign_id)
        if start:
            stmt = stmt.where(MembershipEvent.event_timestamp >= start)
        if end:
            stmt = stmt.where(MembershipEvent.event_timestamp < end)
        return int(db.scalar(stmt) or 0)

    event_total = int(db.scalar(select(func.count()).select_from(MembershipEvent)) or 0)
    telegram_ready = get_settings().telegram_configured
    membership_state = "known" if telegram_ready or event_total else "missing"
    membership_note = (
        None
        if membership_state == "known"
        else "Telegram is not configured and no membership events are stored. This is missing data, not a count of non-members."
    )
    if membership_state == "known":
        membership_note = "Counts recorded Telegram events only. The Bot API does not provide a historical census of the channel."

    attributed = events("join", True) if membership_state == "known" else None
    unattributed = events("join", False) if membership_state == "known" else None
    departures = events("leave", None) if membership_state == "known" else None
    joins_for_net = (attributed or 0) + (unattributed or 0)
    net = None if membership_state == "missing" else joins_for_net - (departures or 0)

    if attempted == 0:
        conversion = None
        conversion_state = "zero_denominator"
        conversion_note = "No invitations have been attempted in this window."
    else:
        conversion = round(((attributed or 0) / attempted) * 100, 2) if attributed is not None else None
        conversion_state = "known" if attributed is not None else "missing"
        conversion_note = membership_note

    cost_stmt = select(func.sum(Campaign.actual_cost_cents), func.count(Campaign.actual_cost_cents)).where(
        Campaign.actual_cost_cents.is_not(None)
    )
    if campaign_id:
        cost_stmt = cost_stmt.where(Campaign.id == campaign_id)
    cost_sum, cost_rows = db.execute(cost_stmt).one()
    if not cost_rows:
        cost_value, cost_state, cost_note = None, "missing", "No campaign has an actual cost recorded."
    elif not attributed:
        cost_value, cost_state, cost_note = None, "zero_denominator", "Cost is recorded but there is no attributed join to divide by."
    else:
        cost_value = round((cost_sum or 0) / attributed / 100, 2)
        cost_state, cost_note = "known", "Sum of actual campaign cost divided by attributed joins."

    if attempted == 0:
        failure_value, failure_state, failure_note = None, "zero_denominator", "No outreach attempts in this window."
    else:
        failure_value = round((failed / attempted) * 100, 2)
        failure_state, failure_note = "known", "Failed attempts divided by attempts that left the queue."

    base_def = {"time_window": window, "filters": {k: v for k, v in params.items() if v}}
    cards = [
        metric("imported_contacts", "Total imported contacts", total, "known", {**base_def, "numerator": "Contacts created in the window", "denominator": None, "event_source": "contacts"}),
        metric("unique_valid_contacts", "Unique valid contacts", total, "known", {**base_def, "numerator": "Stored contacts, which are unique on a keyed phone hash", "denominator": None, "event_source": "contacts"}),
        metric("eligible_contacts", "Eligible contacts", eligible, "known", {**base_def, "numerator": "Contacts currently in ELIGIBLE lifecycle status", "denominator": None, "event_source": "contacts"}),
        metric("pending_consent", "Pending consent", pending, "known", {**base_def, "numerator": "Contacts whose summary consent status is pending", "denominator": None, "event_source": "contacts"}),
        metric("suppressed_contacts", "Suppressed contacts", suppressed, "known", {**base_def, "numerator": "Contacts with an active suppression record", "denominator": None, "event_source": "contacts"}),
        metric("invitations_attempted", "Invitations attempted", attempted, "known", {**base_def, "numerator": "Invitations in attempted, accepted, delivered, or failed", "denominator": None, "event_source": "invitations"}),
        metric("invitations_accepted", "Accepted by provider", accepted, "known", {**base_def, "numerator": "Invitations accepted by the provider or later delivery-confirmed", "denominator": None, "event_source": "invitations"}),
        metric("delivery_confirmations", "Delivery confirmations", delivered, "known", {**base_def, "numerator": "Invitations with provider delivery confirmation", "denominator": None, "event_source": "provider_messages via invitation status"}),
        metric("attributed_joins", "Attributed joins", attributed, membership_state, {**base_def, "numerator": "Join events with a campaign id", "denominator": None, "event_source": "membership_events"}, membership_note),
        metric("unattributed_joins", "Unattributed joins", unattributed, membership_state, {**base_def, "numerator": "Join events without a campaign id", "denominator": None, "event_source": "membership_events"}, membership_note),
        metric("verified_departures", "Verified departures", departures, membership_state, {**base_def, "numerator": "Leave events supplied by Telegram or reconciliation", "denominator": None, "event_source": "membership_events"}, membership_note),
        metric("net_channel_growth", "Net channel growth", net, membership_state, {**base_def, "numerator": "Recorded joins minus recorded departures", "denominator": None, "event_source": "membership_events"}, membership_note),
        metric("conversion_rate", "Conversion rate", conversion, conversion_state, {**base_def, "numerator": "Attributed joins", "denominator": "Invitations attempted", "event_source": "membership_events / invitations"}, conversion_note),
        metric("cost_per_attributed_join", "Cost per attributed join", cost_value, cost_state, {**base_def, "numerator": "Sum of actual_cost_cents", "denominator": "Attributed joins", "event_source": "campaigns / membership_events"}, cost_note),
        metric("provider_failure_rate", "Provider failure rate", failure_value, failure_state, {**base_def, "numerator": "Failed invitations", "denominator": "Invitations attempted", "event_source": "invitations"}, failure_note),
    ]
    return {"cards": cards, "completeness": "events_only" if membership_state == "known" else "missing"}


def funnel(db: Session, params: dict) -> dict:
    data = overview(db, params)
    by_key = {card["key"]: card["value"] for card in data["cards"]}
    audience = [
        {"key": "imported", "label": "Imported", "count": by_key["imported_contacts"]},
        {"key": "pending_or_known", "label": "Pending consent", "count": by_key["pending_consent"]},
        {"key": "eligible", "label": "Eligible", "count": by_key["eligible_contacts"]},
        {"key": "suppressed", "label": "Suppressed", "count": by_key["suppressed_contacts"]},
    ]
    invitation = [
        {"key": "attempted", "label": "Attempted", "count": by_key["invitations_attempted"]},
        {"key": "accepted", "label": "Accepted by provider", "count": by_key["invitations_accepted"]},
        {"key": "delivered", "label": "Delivery confirmed", "count": by_key["delivery_confirmations"]},
        {"key": "attributed_joins", "label": "Attributed joins", "count": by_key["attributed_joins"]},
    ]
    return {"audience": audience, "invitation": invitation, "notes": data["completeness"]}


def campaign_comparison(db: Session, params: dict) -> dict:
    status = params.get("campaign_status")
    stmt = select(Campaign)
    if status:
        stmt = stmt.where(Campaign.status == status)
    if params.get("campaign_id"):
        stmt = stmt.where(Campaign.id == params["campaign_id"])
    rows = []
    for campaign in db.scalars(stmt.order_by(Campaign.created_at.desc())):
        attempted = int(
            db.scalar(
                select(func.count()).select_from(Invitation).where(
                    Invitation.campaign_id == campaign.id,
                    Invitation.status.in_(ATTEMPTED),
                )
            )
            or 0
        )
        joins = int(
            db.scalar(
                select(func.count()).select_from(MembershipEvent).where(
                    MembershipEvent.campaign_id == campaign.id,
                    MembershipEvent.event_type == "join",
                )
            )
            or 0
        )
        conversion = round(joins / attempted * 100, 2) if attempted else None
        cost = None
        cost_state = "missing" if campaign.actual_cost_cents is None else "known"
        if campaign.actual_cost_cents is None:
            cost_state = "missing"
        elif joins == 0:
            cost_state = "zero_denominator"
        else:
            cost = round(campaign.actual_cost_cents / joins / 100, 2)
        rows.append(
            {
                "id": campaign.id,
                "name": campaign.name,
                "status": campaign.status,
                "channel": campaign.outreach_channel,
                "is_demo": campaign.is_demo,
                "invitations_attempted": attempted,
                "attributed_joins": joins,
                "conversion_rate": conversion,
                "conversion_state": "known" if attempted else "zero_denominator",
                "cost_per_join": cost,
                "cost_state": cost_state,
                "actual_cost": None if campaign.actual_cost_cents is None else campaign.actual_cost_cents / 100,
            }
        )
    return {"campaigns": rows}


def membership_series(db: Session, params: dict) -> dict:
    start = _parse_dt(params.get("from")) or (datetime.now(timezone.utc) - timedelta(days=30))
    end = _parse_dt(params.get("to"), end=True) or datetime.now(timezone.utc)
    events = list(
        db.scalars(
            select(MembershipEvent).where(
                MembershipEvent.event_timestamp >= start,
                MembershipEvent.event_timestamp < end,
                MembershipEvent.event_type.in_(["join", "leave"]),
            )
        )
    )
    daily: dict[str, dict] = {}
    cursor = start.date()
    last = (end - timedelta(seconds=1)).date()
    while cursor <= last:
        daily[cursor.isoformat()] = {"date": cursor.isoformat(), "joins": 0, "departures": 0, "attributed_joins": 0}
        cursor += timedelta(days=1)
    for event in events:
        stamp = event.event_timestamp
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        key = stamp.date().isoformat()
        bucket = daily.setdefault(key, {"date": key, "joins": 0, "departures": 0, "attributed_joins": 0})
        if event.event_type == "join":
            bucket["joins"] += 1
            if event.campaign_id:
                bucket["attributed_joins"] += 1
        elif event.event_type == "leave":
            bucket["departures"] += 1
    points = [daily[key] for key in sorted(daily)]
    weekly: dict[str, dict] = {}
    for point in points:
        day = datetime.fromisoformat(point["date"]).date()
        week = (day - timedelta(days=day.weekday())).isoformat()
        bucket = weekly.setdefault(week, {"week": week, "joins": 0, "departures": 0, "attributed_joins": 0})
        bucket["joins"] += point["joins"]
        bucket["departures"] += point["departures"]
        bucket["attributed_joins"] += point["attributed_joins"]
    return {
        "daily": points,
        "weekly": [weekly[key] for key in sorted(weekly)],
        "completeness": "partial",
        "note": "Series include only events the bot received or reconciliation verified. Missing history stays missing.",
    }


def status_distribution(db: Session) -> dict:
    rows = db.execute(
        select(Contact.lifecycle_status, func.count()).where(Contact.erased_at.is_(None)).group_by(Contact.lifecycle_status)
    ).all()
    membership = db.execute(
        select(Contact.membership_status, func.count()).where(Contact.erased_at.is_(None)).group_by(Contact.membership_status)
    ).all()
    return {
        "lifecycle": [{"status": status, "count": count} for status, count in rows],
        "membership": [{"status": status, "count": count} for status, count in membership],
    }


def provider_performance(db: Session) -> dict:
    rows = db.execute(
        select(Invitation.provider, Invitation.status, func.count()).group_by(Invitation.provider, Invitation.status)
    ).all()
    grouped: dict[str, dict] = {}
    for provider, status, count in rows:
        bucket = grouped.setdefault(provider or "unspecified", {"provider": provider or "unspecified", "statuses": {}})
        bucket["statuses"][status] = count
    return {"providers": list(grouped.values())}


def retention(db: Session) -> dict:
    joins = list(db.scalars(select(MembershipEvent).where(MembershipEvent.event_type == "join")))
    if not joins:
        return {
            "cohorts": [],
            "completeness": "missing",
            "note": "No join events are stored, so retention cannot be calculated. This is missing data.",
        }
    cohorts: dict[str, dict] = {}
    for event in joins:
        if not event.telegram_user_id:
            continue
        stamp = event.event_timestamp
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        week = (stamp.date() - timedelta(days=stamp.date().weekday())).isoformat()
        bucket = cohorts.setdefault(week, {"week": week, "joined": set(), "departed": set()})
        bucket["joined"].add(event.telegram_user_id)
    leaves = list(db.scalars(select(MembershipEvent).where(MembershipEvent.event_type == "leave")))
    for event in leaves:
        if not event.telegram_user_id:
            continue
        for bucket in cohorts.values():
            if event.telegram_user_id in bucket["joined"]:
                bucket["departed"].add(event.telegram_user_id)
    payload = []
    for week in sorted(cohorts):
        bucket = cohorts[week]
        joined = len(bucket["joined"])
        retained = len(bucket["joined"] - bucket["departed"])
        payload.append(
            {
                "week": week,
                "joined": joined,
                "retained": retained,
                "retention_rate": round(retained / joined * 100, 2) if joined else None,
            }
        )
    return {
        "cohorts": payload,
        "completeness": "partial",
        "note": "Retention uses recorded joins and later leave events for the same Telegram user. Missed leave events overstate retention.",
    }
