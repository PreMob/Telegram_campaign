"""Normalized persistence model for the audience platform."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class UserRoleName(str, enum.Enum):
    super_admin = "super_admin"
    campaign_manager = "campaign_manager"
    analyst = "analyst"
    read_only = "read_only"


class ConsentState(str, enum.Enum):
    pending = "pending"
    granted = "granted"
    withdrawn = "withdrawn"
    expired = "expired"


class MembershipState(str, enum.Enum):
    unknown = "unknown"
    joined_attributed = "joined_attributed"
    joined_unattributed = "joined_unattributed"
    left = "left"
    confirmed_non_member = "confirmed_non_member"


class LifecycleState(str, enum.Enum):
    imported = "IMPORTED"
    consent_pending = "CONSENT_PENDING"
    eligible = "ELIGIBLE"
    invite_queued = "INVITE_QUEUED"
    invite_attempted = "INVITE_ATTEMPTED"
    invite_sent = "INVITE_SENT"
    delivery_confirmed = "DELIVERY_CONFIRMED"
    joined_attributed = "JOINED_ATTRIBUTED"
    joined_unattributed = "JOINED_UNATTRIBUTED"
    left_channel = "LEFT_CHANNEL"
    not_joined_confirmed = "NOT_JOINED_CONFIRMED"
    unknown = "UNKNOWN"
    suppressed = "SUPPRESSED"
    failed = "FAILED"


class CampaignStatus(str, enum.Enum):
    draft = "draft"
    pending_approval = "pending_approval"
    approved = "approved"
    scheduled = "scheduled"
    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class InvitationStatus(str, enum.Enum):
    queued = "queued"
    attempted = "attempted"
    accepted_by_provider = "accepted_by_provider"
    delivery_confirmed = "delivery_confirmed"
    failed = "failed"
    cancelled = "cancelled"
    suppressed = "suppressed"


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), default="")
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    role: Mapped[Role] = relationship()


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="preview", index=True)
    column_mapping: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    default_region: Mapped[str] = mapped_column(String(8), default="US")
    default_source: Mapped[str] = mapped_column(String(120), default="import")
    apply_consent_column: Mapped[bool] = mapped_column(Boolean, default=False)
    policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    processed_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0)
    inserted_rows: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    storage_path: Mapped[str] = mapped_column(String(500), default="")


class ImportErrorRow(Base):
    __tablename__ = "import_errors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String(64), default="")
    raw_value: Mapped[str] = mapped_column(String(500), default="")
    reason: Mapped[str] = mapped_column(String(500))


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("phone_hmac", name="uq_contacts_phone_hmac"),
        Index("ix_contacts_lifecycle", "lifecycle_status"),
        Index("ix_contacts_membership", "membership_status"),
        Index("ix_contacts_source", "source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    phone_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    phone_hmac: Mapped[str] = mapped_column(String(64), nullable=False)
    phone_last4: Mapped[str] = mapped_column(String(4), default="")
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source: Mapped[str] = mapped_column(String(120), default="import")
    import_batch_id: Mapped[str | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True)
    consent_status: Mapped[str] = mapped_column(String(32), default=ConsentState.pending.value)
    suppression_status: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    communication_preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    last_permitted_outreach_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    membership_status: Mapped[str] = mapped_column(String(40), default=MembershipState.unknown.value)
    last_membership_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(String(40), default=LifecycleState.consent_pending.value)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Consent(Base):
    __tablename__ = "consents"
    __table_args__ = (Index("ix_consents_contact_channel", "contact_id", "channel", "purpose"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"), index=True)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(120), default="")
    policy_version: Mapped[str] = mapped_column(String(64), default="")
    evidence_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SuppressionRecord(Base):
    __tablename__ = "suppression_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"), index=True)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(120), default="operator")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    objective: Mapped[str] = mapped_column(String(255), default="")
    target_audience: Mapped[dict] = mapped_column(JSON, default=dict)
    outreach_channel: Mapped[str] = mapped_column(String(64), default="telegram_invite")
    message_template: Mapped[str] = mapped_column(Text, default="")
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=CampaignStatus.draft.value, index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frequency_cap_days: Mapped[int] = mapped_column(Integer, default=7)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    budget_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispatch_lock: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CampaignAudience(Base):
    __tablename__ = "campaign_audiences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    eligible_count: Mapped[int] = mapped_column(Integer, default=0)
    excluded_count: Mapped[int] = mapped_column(Integer, default=0)
    suppressed_count: Mapped[int] = mapped_column(Integer, default=0)
    unknown_consent_count: Mapped[int] = mapped_column(Integer, default=0)
    unknown_membership_count: Mapped[int] = mapped_column(Integer, default=0)
    joined_excluded_count: Mapped[int] = mapped_column(Integer, default=0)
    rules_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class CampaignLink(Base):
    __tablename__ = "campaign_links"
    __table_args__ = (UniqueConstraint("invite_link", name="uq_campaign_links_url"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    link_name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    invite_link: Mapped[str] = mapped_column(String(500), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_invitations_idempotency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(40), default=InvitationStatus.queued.value, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProviderMessage(Base):
    __tablename__ = "provider_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    invitation_id: Mapped[str] = mapped_column(ForeignKey("invitations.id"), index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TelegramIdentity(Base):
    __tablename__ = "telegram_identities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    telegram_user_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started_bot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContactIdentityLink(Base):
    __tablename__ = "contact_identity_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"), index=True)
    telegram_identity_id: Mapped[str | None] = mapped_column(ForeignKey("telegram_identities.id"), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MembershipEvent(Base):
    __tablename__ = "membership_events"
    __table_args__ = (
        UniqueConstraint("telegram_update_id", name="uq_membership_update"),
        UniqueConstraint("idempotency_key", name="uq_membership_idempotency"),
        Index("ix_membership_campaign", "campaign_id"),
        Index("ix_membership_type_time", "event_type", "event_timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    telegram_update_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    telegram_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    channel_id: Mapped[str] = mapped_column(String(64), default="")
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    invite_link_id: Mapped[str | None] = mapped_column(ForeignKey("campaign_links.id"), nullable=True)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaigns.id"), nullable=True)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processing_status: Mapped[str] = mapped_column(String(32), default="processed")
    error_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="webhook")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookInbox(Base):
    __tablename__ = "webhook_inbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    update_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="received")
    error_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CampaignEvent(Base):
    __tablename__ = "campaign_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_name: Mapped[str] = mapped_column(String(120), index=True)
    celery_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), default="")
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
