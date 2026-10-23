"""Request bodies."""

from datetime import datetime

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=64)


class UserIn(BaseModel):
    email: str
    password: str = Field(min_length=12, max_length=64)
    full_name: str = ""
    role: str


class UserPatch(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    full_name: str | None = None


class ImportCommit(BaseModel):
    mapping: dict
    default_region: str = "US"
    default_source: str = "import"
    apply_consent_column: bool = False
    policy_version: str | None = None


class ConsentIn(BaseModel):
    channel: str
    purpose: str = "channel_invitation"
    source: str
    policy_version: str
    evidence_ref: str | None = None
    expires_at: datetime | None = None


class SuppressIn(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


class CampaignIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str = ""
    objective: str = ""
    target_audience: dict = Field(default_factory=dict)
    outreach_channel: str = "telegram_invite"
    message_template: str = ""
    start_at: datetime | None = None
    end_at: datetime | None = None
    frequency_cap_days: int = Field(default=7, ge=0, le=365)
    budget_cents: int | None = Field(default=None, ge=0)
    actual_cost_cents: int | None = Field(default=None, ge=0)


class CampaignPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = None
    objective: str | None = None
    target_audience: dict | None = None
    outreach_channel: str | None = None
    message_template: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    frequency_cap_days: int | None = Field(default=None, ge=0, le=365)
    budget_cents: int | None = Field(default=None, ge=0)
    actual_cost_cents: int | None = Field(default=None, ge=0)
    status: str | None = None


class LaunchIn(BaseModel):
    confirm: bool = False
    dry_run: bool = False


class PolicyIn(BaseModel):
    policy_version: str = "1"
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    frequency_cap_days: int = Field(default=7, ge=0, le=365)
    default_region: str = "US"


class InviteLinkIn(BaseModel):
    campaign_id: str
