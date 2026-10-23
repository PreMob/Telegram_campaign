"""Versioned HTTP routes."""

import csv
import io
import secrets
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, current_user, require_role
from app.audit import write_audit
from app.config import get_settings
from app.database import get_db
from app.models import (
    AuditLog,
    Campaign,
    CampaignAudience,
    CampaignEvent,
    CampaignLink,
    CampaignStatus,
    Consent,
    ConsentState,
    Contact,
    ContactIdentityLink,
    ImportBatch,
    ImportErrorRow,
    Invitation,
    JobRun,
    MembershipEvent,
    ProviderMessage,
    Role,
    SuppressionRecord,
    SystemSetting,
    User,
    utcnow,
)
from app.rate_limit import allow
from app.schemas import (
    CampaignIn,
    CampaignPatch,
    ConsentIn,
    ImportCommit,
    InviteLinkIn,
    LaunchIn,
    LoginIn,
    PolicyIn,
    SuppressIn,
    UserIn,
    UserPatch,
)
from app.security import (
    can_export,
    can_view_phone,
    create_session_token,
    decrypt_phone,
    hash_password,
    hash_token,
    mask_phone,
    new_csrf,
    verify_password,
)
from app.services.analytics import (
    campaign_comparison,
    funnel,
    membership_series,
    overview,
    provider_performance,
    retention,
    status_distribution,
)
from app.services.campaigns import (
    CampaignError,
    approve_campaign,
    cancel_campaign,
    duplicate_campaign,
    launch_campaign,
    pause_campaign,
    record_preview,
    resume_campaign,
    validate_template,
)
from app.services.imports import preview_file
from app.services.jobs import enqueue_import
from app.services.state import refresh_contact_state
from app.services.telegram_api import TelegramError
from app.services.telegram_service import connection_report, create_campaign_invite, ingest_update

router = APIRouter(prefix="/api/v1")
CHANNELS = {"telegram_invite", "telegram_channel_add", "telegram_dm", "email", "sms", "whatsapp"}
MUTATING_ROLES = ("super_admin", "campaign_manager")


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _user_out(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role.name,
        "is_active": user.is_active,
        "created_at": _iso(user.created_at),
    }


def _phone_fields(contact: Contact, role: str) -> dict:
    masked = f"***{contact.phone_last4}" if contact.phone_last4 else "****"
    if contact.erased_at:
        return {"phone": None, "phone_masked": "erased"}
    payload = {"phone_masked": masked, "phone": None}
    if can_view_phone(role):
        try:
            payload["phone"] = decrypt_phone(contact.phone_ciphertext)
            payload["phone_masked"] = mask_phone(payload["phone"])
        except Exception:
            payload["phone"] = None
    return payload


def _contact_out(contact: Contact, role: str) -> dict:
    return {
        "id": contact.id,
        "name": contact.name,
        "source": contact.source,
        "import_batch_id": contact.import_batch_id,
        "consent_status": contact.consent_status,
        "suppression_status": contact.suppression_status,
        "communication_preferences": {
            key: value
            for key, value in (contact.communication_preferences or {}).items()
            if key != "email"
        },
        "has_email": bool((contact.communication_preferences or {}).get("email")),
        "last_permitted_outreach_at": _iso(contact.last_permitted_outreach_at),
        "membership_status": contact.membership_status,
        "last_membership_event_at": _iso(contact.last_membership_event_at),
        "lifecycle_status": contact.lifecycle_status,
        "is_demo": contact.is_demo,
        "erased_at": _iso(contact.erased_at),
        "created_at": _iso(contact.created_at),
        **_phone_fields(contact, role),
    }


def _campaign_out(db: Session, campaign: Campaign) -> dict:
    link = db.scalar(
        select(CampaignLink)
        .where(CampaignLink.campaign_id == campaign.id, CampaignLink.revoked.is_(False))
        .order_by(CampaignLink.created_at.desc())
    )
    return {
        "id": campaign.id,
        "name": campaign.name,
        "description": campaign.description,
        "objective": campaign.objective,
        "target_audience": campaign.target_audience or {},
        "outreach_channel": campaign.outreach_channel,
        "message_template": campaign.message_template,
        "start_at": _iso(campaign.start_at),
        "end_at": _iso(campaign.end_at),
        "status": campaign.status,
        "created_by": campaign.created_by,
        "approved_by": campaign.approved_by,
        "approved_at": _iso(campaign.approved_at),
        "frequency_cap_days": campaign.frequency_cap_days,
        "budget_cents": campaign.budget_cents,
        "actual_cost_cents": campaign.actual_cost_cents,
        "failure_reason": campaign.failure_reason,
        "archived_at": _iso(campaign.archived_at),
        "is_demo": campaign.is_demo,
        "invite_link": link.invite_link if link else None,
        "invite_link_name": link.link_name if link else None,
        "created_at": _iso(campaign.created_at),
        "updated_at": _iso(campaign.updated_at),
    }


def _get_contact(db: Session, contact_id: str) -> Contact:
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise _error(404, "not_found", "Contact not found")
    return contact


def _get_campaign(db: Session, campaign_id: str) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise _error(404, "not_found", "Campaign not found")
    return campaign


def register(api: APIRouter, get_db) -> None:
    """Bind routes that need the application database dependency."""

    def db_dep(db: Session = Depends(get_db)) -> Session:
        return db

    @api.post("/auth/login")
    def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
        settings = get_settings()
        ip = client_ip(request) or "unknown"
        if not allow(f"login:{ip}", settings.login_rate_limit, settings.login_rate_window_seconds):
            raise _error(429, "rate_limited", "Too many login attempts. Wait a minute and try again.")
        user = db.scalar(select(User).where(User.email == body.email.lower()))
        if user is None or not verify_password(body.password, user.password_hash) or not user.is_active:
            write_audit(db, action="auth.login_failed", entity_type="user", metadata={"email": body.email.lower()}, ip_address=ip)
            db.commit()
            raise _error(401, "invalid_credentials", "Email or password is incorrect")
        from sqlalchemy.orm import joinedload

        user = db.scalar(select(User).options(joinedload(User.role)).where(User.id == user.id))
        csrf = new_csrf()
        token = create_session_token(user.id, user.role.name, csrf)
        write_audit(db, action="auth.login", entity_type="user", entity_id=user.id, actor_id=user.id, ip_address=ip)
        db.commit()
        from fastapi.responses import JSONResponse

        response = JSONResponse(_user_out(user))
        secure = settings.is_production
        max_age = settings.session_hours * 3600
        response.set_cookie("tagp_session", token, httponly=True, samesite="lax", secure=secure, max_age=max_age, path="/")
        response.set_cookie("tagp_csrf", csrf, httponly=False, samesite="lax", secure=secure, max_age=max_age, path="/")
        return response

    @api.post("/auth/logout")
    def logout(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
        write_audit(db, action="auth.logout", entity_type="user", entity_id=user.id, actor_id=user.id, ip_address=client_ip(request))
        db.commit()
        from fastapi.responses import JSONResponse

        response = JSONResponse({"ok": True})
        response.delete_cookie("tagp_session", path="/")
        response.delete_cookie("tagp_csrf", path="/")
        return response

    @api.get("/auth/me")
    def me(user: User = Depends(current_user)):
        return _user_out(user)

    @api.get("/users")
    def list_users(user: User = Depends(require_role("super_admin")), db: Session = Depends(get_db)):
        rows = db.scalars(select(User).join(Role).order_by(User.created_at.desc())).all()
        from sqlalchemy.orm import joinedload

        rows = db.scalars(select(User).options(joinedload(User.role)).order_by(User.created_at.desc())).unique().all()
        return {"items": [_user_out(row) for row in rows]}

    @api.post("/users", status_code=201)
    def create_user(body: UserIn, request: Request, actor: User = Depends(require_role("super_admin")), db: Session = Depends(get_db)):
        if body.role not in {"super_admin", "campaign_manager", "analyst", "read_only"}:
            raise _error(422, "invalid_role", "Unknown role")
        if db.scalar(select(User.id).where(User.email == body.email.lower())):
            raise _error(409, "duplicate", "A user with that email already exists")
        role = db.scalar(select(Role).where(Role.name == body.role))
        try:
            password_hash = hash_password(body.password)
        except ValueError as exc:
            raise _error(422, "invalid_password", str(exc))
        created = User(email=body.email.lower(), password_hash=password_hash, full_name=body.full_name.strip(), role_id=role.id)
        db.add(created)
        db.flush()
        write_audit(db, action="user.create", entity_type="user", entity_id=created.id, actor_id=actor.id, metadata={"role": body.role}, ip_address=client_ip(request))
        db.commit()
        created = db.scalar(select(User).options(__import__("sqlalchemy.orm", fromlist=["joinedload"]).joinedload(User.role)).where(User.id == created.id))
        return _user_out(created)

    @api.patch("/users/{user_id}")
    def patch_user(user_id: str, body: UserPatch, request: Request, actor: User = Depends(require_role("super_admin")), db: Session = Depends(get_db)):
        from sqlalchemy.orm import joinedload

        subject = db.scalar(select(User).options(joinedload(User.role)).where(User.id == user_id))
        if subject is None:
            raise _error(404, "not_found", "User not found")
        if body.role:
            role = db.scalar(select(Role).where(Role.name == body.role))
            if role is None:
                raise _error(422, "invalid_role", "Unknown role")
            subject.role_id = role.id
        if body.is_active is not None:
            if subject.id == actor.id and not body.is_active:
                raise _error(409, "invalid_status", "You cannot deactivate your own account")
            subject.is_active = body.is_active
        if body.full_name is not None:
            subject.full_name = body.full_name
        subject.updated_at = utcnow()
        write_audit(db, action="user.update", entity_type="user", entity_id=subject.id, actor_id=actor.id, ip_address=client_ip(request))
        db.commit()
        subject = db.scalar(select(User).options(joinedload(User.role)).where(User.id == user_id))
        return _user_out(subject)

    @api.post("/imports", status_code=201)
    def create_import(
        request: Request,
        file: UploadFile = File(...),
        user: User = Depends(require_role(*MUTATING_ROLES)),
        db: Session = Depends(get_db),
    ):
        name = (file.filename or "contacts.csv").lower()
        if not name.endswith((".csv", ".xlsx")):
            raise _error(422, "invalid_file", "Upload a CSV or XLSX file")
        content = file.file.read(26 * 1024 * 1024)
        if len(content) >= 26 * 1024 * 1024:
            raise _error(413, "file_too_large", "Import files must be 25 MB or smaller")
        settings = get_settings()
        folder = Path(settings.data_dir) / "uploads"
        folder.mkdir(parents=True, exist_ok=True)
        batch = ImportBatch(filename=Path(file.filename or "contacts.csv").name[:200], status="preview", created_by=user.id)
        db.add(batch)
        db.flush()
        path = folder / f"{batch.id}{Path(name).suffix}"
        path.write_bytes(content)
        batch.storage_path = str(path)
        try:
            preview = preview_file(path)
        except Exception:
            batch.status = "failed"
            batch.error_summary = "The file could not be read"
            db.commit()
            raise _error(422, "invalid_file", "The file could not be read as CSV or XLSX")
        write_audit(db, action="import.preview", entity_type="import_batch", entity_id=batch.id, actor_id=user.id, metadata={"rows": preview["row_count_estimate"]}, ip_address=client_ip(request))
        db.commit()
        return {"id": batch.id, "filename": batch.filename, "status": batch.status, **preview}

    @api.post("/imports/{batch_id}/commit", status_code=202)
    def commit_import(batch_id: str, body: ImportCommit, request: Request, user: User = Depends(require_role(*MUTATING_ROLES)), db: Session = Depends(get_db)):
        batch = db.get(ImportBatch, batch_id)
        if batch is None:
            raise _error(404, "not_found", "Import not found")
        if "phone" not in body.mapping or not body.mapping.get("phone"):
            raise _error(422, "mapping_required", "Map a column to the phone field")
        batch.column_mapping = body.mapping
        batch.default_region = body.default_region or "US"
        batch.default_source = body.default_source or "import"
        batch.apply_consent_column = body.apply_consent_column
        batch.policy_version = body.policy_version
        batch.status = "queued"
        write_audit(
            db,
            action="import.commit",
            entity_type="import_batch",
            entity_id=batch.id,
            actor_id=user.id,
            metadata={"apply_consent_column": body.apply_consent_column},
            ip_address=client_ip(request),
        )
        db.commit()
        enqueue_import(batch.id)
        db.refresh(batch)
        return _batch_out(batch)

    @api.post("/imports/{batch_id}/cancel")
    def cancel_import(batch_id: str, user: User = Depends(require_role(*MUTATING_ROLES)), db: Session = Depends(get_db)):
        batch = db.get(ImportBatch, batch_id)
        if batch is None:
            raise _error(404, "not_found", "Import not found")
        batch.cancel_requested = True
        if batch.status in {"preview", "queued"}:
            batch.status = "cancelled"
            batch.completed_at = utcnow()
        db.commit()
        return _batch_out(batch)

    @api.get("/imports")
    def list_imports(user: User = Depends(current_user), db: Session = Depends(get_db)):
        rows = db.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(100)).all()
        return {"items": [_batch_out(row) for row in rows]}

    @api.get("/imports/{batch_id}")
    def get_import(batch_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
        batch = db.get(ImportBatch, batch_id)
        if batch is None:
            raise _error(404, "not_found", "Import not found")
        return _batch_out(batch)

    @api.get("/imports/{batch_id}/errors")
    def import_errors(batch_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
        batch = db.get(ImportBatch, batch_id)
        if batch is None:
            raise _error(404, "not_found", "Import not found")
        rows = db.scalars(select(ImportErrorRow).where(ImportErrorRow.batch_id == batch_id).order_by(ImportErrorRow.row_number)).all()
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["row_number", "field", "raw_value", "reason"])
        for row in rows:
            writer.writerow([row.row_number, row.field, _csv_safe(row.raw_value), _csv_safe(row.reason)])
        return Response(buffer.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="import-{batch_id}-errors.csv"'})

    @api.get("/contacts")
    def list_contacts(
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
        q: str | None = None,
        source: str | None = None,
        consent_status: str | None = None,
        suppression: bool | None = None,
        membership_status: str | None = None,
        lifecycle_status: str | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(25, ge=1, le=100),
        sort: str = "created_at",
        direction: str = "desc",
    ):
        stmt = select(Contact).where(Contact.erased_at.is_(None))
        if source:
            stmt = stmt.where(Contact.source == source)
        if consent_status:
            stmt = stmt.where(Contact.consent_status == consent_status)
        if suppression is not None:
            stmt = stmt.where(Contact.suppression_status.is_(suppression))
        if membership_status:
            stmt = stmt.where(Contact.membership_status == membership_status)
        if lifecycle_status:
            stmt = stmt.where(Contact.lifecycle_status == lifecycle_status)
        if q:
            like = f"%{q.strip()}%"
            filters = [Contact.name.ilike(like), Contact.phone_last4 == q.strip()[-4:]]
            stmt = stmt.where(or_(*filters))
        sort_columns = {
            "created_at": Contact.created_at,
            "name": Contact.name,
            "lifecycle_status": Contact.lifecycle_status,
            "membership_status": Contact.membership_status,
        }
        column = sort_columns.get(sort, Contact.created_at)
        stmt = stmt.order_by(column.asc() if direction == "asc" else column.desc())
        total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
        return {"items": [_contact_out(row, user.role.name) for row in rows], "page": page, "page_size": page_size, "total": total}

    @api.get("/contacts/export")
    def export_contacts(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
        if not can_export(user.role.name):
            raise _error(403, "forbidden", "Your role cannot export contacts")
        write_audit(db, action="contacts.export", entity_type="contact", actor_id=user.id, ip_address=client_ip(request))
        db.commit()

        def generate():
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["id", "phone", "name", "source", "consent_status", "suppression_status", "membership_status", "lifecycle_status", "is_demo"])
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
            rows = db.scalars(select(Contact).where(Contact.erased_at.is_(None)).order_by(Contact.created_at)).all()
            for contact in rows:
                phone = ""
                try:
                    phone = decrypt_phone(contact.phone_ciphertext)
                except Exception:
                    phone = ""
                writer.writerow([
                    contact.id,
                    _csv_safe(phone),
                    _csv_safe(contact.name or ""),
                    _csv_safe(contact.source),
                    contact.consent_status,
                    contact.suppression_status,
                    contact.membership_status,
                    contact.lifecycle_status,
                    contact.is_demo,
                ])
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)

        return StreamingResponse(generate(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="contacts.csv"'})

    @api.get("/contacts/{contact_id}")
    def get_contact(contact_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
        contact = _get_contact(db, contact_id)
        refresh_contact_state(db, contact)
        db.commit()
        return _contact_out(contact, user.role.name)

    @api.get("/contacts/{contact_id}/timeline")
    def timeline(contact_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
        contact = _get_contact(db, contact_id)
        events = []
        events.append({"at": _iso(contact.created_at), "type": "imported", "summary": f"Imported from {contact.source}", "details": {"demo": contact.is_demo}})
        for consent in db.scalars(select(Consent).where(Consent.contact_id == contact.id)):
            events.append({"at": _iso(consent.created_at), "type": "consent", "summary": f"{consent.status} for {consent.channel}", "details": {"purpose": consent.purpose, "source": consent.source, "policy_version": consent.policy_version, "withdrawn_at": _iso(consent.withdrawn_at)}})
        for record in db.scalars(select(SuppressionRecord).where(SuppressionRecord.contact_id == contact.id)):
            events.append({"at": _iso(record.created_at), "type": "suppression", "summary": record.reason, "details": {"active": record.active, "source": record.source}})
        for invitation in db.scalars(select(Invitation).where(Invitation.contact_id == contact.id)):
            events.append({"at": _iso(invitation.created_at), "type": "invitation", "summary": f"{invitation.status} via {invitation.channel}", "details": {"provider": invitation.provider, "error": invitation.error}})
            for message in db.scalars(select(ProviderMessage).where(ProviderMessage.invitation_id == invitation.id)):
                events.append({"at": _iso(message.created_at), "type": "provider", "summary": message.state, "details": message.detail})
        identity_ids = list(db.scalars(select(ContactIdentityLink.telegram_identity_id).where(ContactIdentityLink.contact_id == contact.id, ContactIdentityLink.telegram_identity_id.is_not(None))))
        for link in db.scalars(select(ContactIdentityLink).where(ContactIdentityLink.contact_id == contact.id)):
            events.append({"at": _iso(link.used_at or link.created_at), "type": "identity_link", "summary": "Voluntary Telegram link used" if link.used_at else "Link code created", "details": {"expires_at": _iso(link.expires_at)}})
        if identity_ids:
            from app.models import TelegramIdentity

            user_ids = list(db.scalars(select(TelegramIdentity.telegram_user_id).where(TelegramIdentity.id.in_(identity_ids))))
            if user_ids:
                for membership in db.scalars(select(MembershipEvent).where(MembershipEvent.telegram_user_id.in_(user_ids))):
                    events.append({"at": _iso(membership.event_timestamp), "type": "membership", "summary": membership.event_type, "details": {"campaign_id": membership.campaign_id, "source": membership.source, "new_status": membership.new_status}})
        for audit in db.scalars(select(AuditLog).where(AuditLog.entity_type == "contact", AuditLog.entity_id == contact.id)):
            events.append({"at": _iso(audit.created_at), "type": "audit", "summary": audit.action, "details": audit.metadata_json})
        events.sort(key=lambda item: item["at"] or "", reverse=True)
        return {"contact_id": contact.id, "events": events}

    @api.get("/contacts/{contact_id}/consents")
    def list_consents(contact_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
        _get_contact(db, contact_id)
        rows = db.scalars(select(Consent).where(Consent.contact_id == contact_id).order_by(Consent.created_at.desc())).all()
        return {"items": [_consent_out(row) for row in rows]}

    @api.post("/contacts/{contact_id}/consents", status_code=201)
    def grant_consent(contact_id: str, body: ConsentIn, request: Request, user: User = Depends(require_role(*MUTATING_ROLES)), db: Session = Depends(get_db)):
        contact = _get_contact(db, contact_id)
        if body.channel not in CHANNELS:
            raise _error(422, "invalid_channel", "Unknown communication channel")
        if contact.erased_at:
            raise _error(409, "erased", "This contact has been erased")
        consent = Consent(contact_id=contact.id, channel=body.channel, purpose=body.purpose, status=ConsentState.granted.value, source=body.source, policy_version=body.policy_version, evidence_ref=body.evidence_ref, expires_at=body.expires_at)
        db.add(consent)
        db.flush()
        refresh_contact_state(db, contact)
        write_audit(db, action="consent.grant", entity_type="contact", entity_id=contact.id, actor_id=user.id, metadata={"channel": body.channel, "policy_version": body.policy_version}, ip_address=client_ip(request))
        db.commit()
        return _consent_out(consent)

    @api.post("/contacts/{contact_id}/consents/{consent_id}/withdraw")
    def withdraw_consent(contact_id: str, consent_id: str, request: Request, user: User = Depends(require_role(*MUTATING_ROLES)), db: Session = Depends(get_db)):
        contact = _get_contact(db, contact_id)
        consent = db.get(Consent, consent_id)
        if consent is None or consent.contact_id != contact.id:
            raise _error(404, "not_found", "Consent record not found")
        if consent.status != ConsentState.withdrawn.value:
            consent.status = ConsentState.withdrawn.value
            consent.withdrawn_at = utcnow()
            db.add(SuppressionRecord(contact_id=contact.id, reason="consent_withdrawn", source="consent_withdrawal", active=True, created_by=user.id))
        refresh_contact_state(db, contact)
        write_audit(db, action="consent.withdraw", entity_type="contact", entity_id=contact.id, actor_id=user.id, metadata={"channel": consent.channel}, ip_address=client_ip(request))
        db.commit()
        return _consent_out(consent)

    @api.post("/contacts/{contact_id}/suppress")
    def suppress(contact_id: str, body: SuppressIn, request: Request, user: User = Depends(require_role(*MUTATING_ROLES)), db: Session = Depends(get_db)):
        contact = _get_contact(db, contact_id)
        db.add(SuppressionRecord(contact_id=contact.id, reason=body.reason, source="operator", active=True, created_by=user.id))
        db.flush()
        refresh_contact_state(db, contact)
        write_audit(db, action="contact.suppress", entity_type="contact", entity_id=contact.id, actor_id=user.id, ip_address=client_ip(request))
        db.commit()
        return _contact_out(contact, user.role.name)

    @api.post("/contacts/{contact_id}/unsuppress")
    def unsuppress(contact_id: str, request: Request, user: User = Depends(require_role("super_admin")), db: Session = Depends(get_db)):
        contact = _get_contact(db, contact_id)
        rows = db.scalars(select(SuppressionRecord).where(SuppressionRecord.contact_id == contact.id, SuppressionRecord.active.is_(True))).all()
        for row in rows:
            row.active = False
            row.released_at = utcnow()
        refresh_contact_state(db, contact)
        write_audit(db, action="contact.unsuppress", entity_type="contact", entity_id=contact.id, actor_id=user.id, metadata={"released": len(rows)}, ip_address=client_ip(request))
        db.commit()
        return _contact_out(contact, user.role.name)

    @api.post("/contacts/{contact_id}/erase")
    def erase(contact_id: str, request: Request, user: User = Depends(require_role("super_admin")), db: Session = Depends(get_db)):
        contact = _get_contact(db, contact_id)
        tombstone = f"erased-{secrets.token_hex(16)}"
        from app.security import encrypt_phone, phone_hmac

        contact.phone_ciphertext = encrypt_phone("erased")
        contact.phone_hmac = phone_hmac(tombstone)
        contact.phone_last4 = ""
        contact.name = None
        contact.communication_preferences = {}
        contact.erased_at = utcnow()
        refresh_contact_state(db, contact)
        write_audit(db, action="contact.erase", entity_type="contact", entity_id=contact.id, actor_id=user.id, ip_address=client_ip(request))
        db.commit()
        return _contact_out(contact, user.role.name)

    @api.post("/contacts/{contact_id}/identity-link", status_code=201)
    def identity_link(contact_id: str, request: Request, user: User = Depends(require_role(*MUTATING_ROLES)), db: Session = Depends(get_db)):
        contact = _get_contact(db, contact_id)
        if contact.erased_at:
            raise _error(409, "erased", "This contact has been erased")
        token = secrets.token_urlsafe(24)
        record = ContactIdentityLink(contact_id=contact.id, token_hash=hash_token(token), expires_at=utcnow() + timedelta(days=7), created_by=user.id)
        db.add(record)
        write_audit(db, action="identity_link.create", entity_type="contact", entity_id=contact.id, actor_id=user.id, ip_address=client_ip(request))
        db.commit()
        return {
            "expires_at": _iso(record.expires_at),
            "token": token,
            "instructions": "Ask the person to open the bot and send /start followed by this code. The code is single-use, expires in 7 days, and does not contain their phone number.",
        }

    @api.get("/campaigns")
    def list_campaigns(
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
        status: str | None = None,
        include_archived: bool = False,
        page: int = Query(1, ge=1),
        page_size: int = Query(25, ge=1, le=100),
    ):
        stmt = select(Campaign)
        if status:
            stmt = stmt.where(Campaign.status == status)
        if not include_archived:
            stmt = stmt.where(Campaign.archived_at.is_(None))
        total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = db.scalars(stmt.order_by(Campaign.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
        return {"items": [_campaign_out(db, row) for row in rows], "page": page, "page_size": page_size, "total": total}

    @api.post("/campaigns", status_code=201)
    def create_campaign(body: CampaignIn, request: Request, user: User = Depends(require_role(*MUTATING_ROLES)), db: Session = Depends(get_db)):
        _validate_campaign_body(body)
        campaign = Campaign(
            name=body.name.strip(),
            description=body.description,
            objective=body.objective,
            target_audience=body.target_audience,
            outreach_channel=body.outreach_channel,
            message_template=body.message_template,
            start_at=body.start_at,
            end_at=body.end_at,
            status=CampaignStatus.draft.value,
            created_by=user.id,
            frequency_cap_days=body.frequency_cap_days,
            budget_cents=body.budget_cents,
            actual_cost_cents=body.actual_cost_cents,
        )
        db.add(campaign)
        db.flush()
        from app.services.campaigns import add_event

        add_event(db, campaign, user.id, "created", {})
        write_audit(db, action="campaign.create", entity_type="campaign", entity_id=campaign.id, actor_id=user.id, ip_address=client_ip(request))
        db.commit()
        return _campaign_out(db, campaign)

    @api.get("/campaigns/{campaign_id}")
    def get_campaign(campaign_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
        campaign = _get_campaign(db, campaign_id)
        events = db.scalars(select(CampaignEvent).where(CampaignEvent.campaign_id == campaign.id).order_by(CampaignEvent.created_at.desc()).limit(50)).all()
        audiences = db.scalars(select(CampaignAudience).where(CampaignAudience.campaign_id == campaign.id).order_by(CampaignAudience.created_at.desc()).limit(5)).all()
        payload = _campaign_out(db, campaign)
        payload["events"] = [{"at": _iso(event.created_at), "type": event.event_type, "actor_id": event.actor_id, "details": event.details} for event in events]
        payload["previews"] = [
            {"at": _iso(row.created_at), "eligible": row.eligible_count, "excluded": row.excluded_count, "suppressed": row.suppressed_count, "unknown_consent": row.unknown_consent_count, "unknown_membership": row.unknown_membership_count}
            for row in audiences
        ]
        return payload

    @api.patch("/campaigns/{campaign_id}")
    def patch_campaign(campaign_id: str, body: CampaignPatch, request: Request, user: User = Depends(require_role(*MUTATING_ROLES)), db: Session = Depends(get_db)):
        campaign = _get_campaign(db, campaign_id)
        if campaign.status not in {CampaignStatus.draft.value, CampaignStatus.pending_approval.value}:
            raise _error(409, "invalid_status", "Only draft or pending campaigns can be edited")
        data = body.model_dump(exclude_unset=True)
        if "message_template" in data:
            validate_template(data["message_template"] or "")
        if "outreach_channel" in data and data["outreach_channel"] not in CHANNELS:
            raise _error(422, "invalid_channel", "Unknown outreach channel")
        for field in ("name", "description", "objective", "target_audience", "outreach_channel", "message_template", "start_at", "end_at", "frequency_cap_days", "budget_cents", "actual_cost_cents"):
            if field in data:
                setattr(campaign, field, data[field])
        if data.get("status") == CampaignStatus.pending_approval.value and campaign.status == CampaignStatus.draft.value:
            campaign.status = CampaignStatus.pending_approval.value
        elif "status" in data and data["status"] != campaign.status:
            raise _error(409, "invalid_status", "Use the approval and launch actions to change status")
        campaign.updated_at = utcnow()
        write_audit(db, action="campaign.update", entity_type="campaign", entity_id=campaign.id, actor_id=user.id, ip_address=client_ip(request))
        db.commit()
        return _campaign_out(db, campaign)

    @api.post("/campaigns/{campaign_id}/preview")
    def preview_campaign(campaign_id: str, user: User = Depends(require_role(*MUTATING_ROLES)), db: Session = Depends(get_db)):
        campaign = _get_campaign(db, campaign_id)
        summary = record_preview(db, campaign, user.id)
        db.commit()
        summary.pop("eligible_ids", None)
        return summary

    @api.post("/campaigns/{campaign_id}/approve")
    def approve(campaign_id: str, user: User = Depends(require_role("super_admin", "campaign_manager")), db: Session = Depends(get_db)):
        campaign = _get_campaign(db, campaign_id)
        try:
            approve_campaign(db, campaign, user)
            db.commit()
        except CampaignError as exc:
            db.rollback()
            raise _error(exc.status_code, exc.code, str(exc))
        return _campaign_out(db, campaign)

    @api.post("/campaigns/{campaign_id}/launch")
    def launch(campaign_id: str, body: LaunchIn, user: User = Depends(require_role(*MUTATING_ROLES)), db: Session = Depends(get_db)):
        campaign = _get_campaign(db, campaign_id)
        try:
            result = launch_campaign(db, campaign, user, confirm=body.confirm, dry_run=body.dry_run)
        except CampaignError as exc:
            db.rollback()
            raise _error(exc.status_code, exc.code, str(exc))
        except TelegramError as exc:
            db.rollback()
            code = "telegram_error"
            raise _error(422, code, str(exc))
        db.refresh(campaign)
        result["campaign"] = _campaign_out(db, campaign)
        return result

    @api.post("/campaigns/{campaign_id}/pause")
    def pause(campaign_id: str, user: User = Depends(require_role(*MUTATING_ROLES)), db: Session = Depends(get_db)):
        campaign = _get_campaign(db, campaign_id)
        try:
            pause_campaign(db, campaign, user)
            db.commit()
        except CampaignError as exc:
            db.rollback()
            raise _error(exc.status_code, exc.code, str(exc))
        return _campaign_out(db, campaign)

    @api.post("/campaigns/{campaign_id}/resume")
    def resume(campaign_id: str, user: User = Depends(require_role(*MUTATING_ROLES)), db: Session = Depends(get_db)):
        campaign = _get_campaign(db, campaign_id)
        try:
            resume_campaign(db, campaign, user)
        except CampaignError as exc:
            db.rollback()
            raise _error(exc.status_code, exc.code, str(exc))
        db.refresh(campaign)
        return _campaign_out(db, campaign)

    @api.post("/campaigns/{campaign_id}/cancel")
    def cancel(campaign_id: str, user: User = Depends(require_role(*MUTATING_ROLES)), db: Session = Depends(get_db)):
        campaign = _get_campaign(db, campaign_id)
        try:
            cancel_campaign(db, campaign, user)
            db.commit()
        except CampaignError as exc:
            db.rollback()
            raise _error(exc.status_code, exc.code, str(exc))
        return _campaign_out(db, campaign)

    @api.post("/campaigns/{campaign_id}/duplicate", status_code=201)
    def duplicate(campaign_id: str, user: User = Depends(require_role(*MUTATING_ROLES)), db: Session = Depends(get_db)):
        campaign = _get_campaign(db, campaign_id)
        copy = duplicate_campaign(db, campaign, user)
        db.commit()
        return _campaign_out(db, copy)

    @api.post("/campaigns/{campaign_id}/archive")
    def archive(campaign_id: str, user: User = Depends(require_role(*MUTATING_ROLES)), db: Session = Depends(get_db)):
        campaign = _get_campaign(db, campaign_id)
        if campaign.status == CampaignStatus.running.value:
            raise _error(409, "invalid_status", "Pause or cancel a running campaign before archiving it")
        campaign.archived_at = utcnow()
        db.commit()
        return _campaign_out(db, campaign)

    @api.get("/integrations/telegram/status")
    def telegram_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
        report = connection_report(db)
        report.pop("bot_id", None)
        return report

    @api.post("/integrations/telegram/test")
    def telegram_test(user: User = Depends(require_role(*MUTATING_ROLES)), db: Session = Depends(get_db)):
        try:
            report = connection_report(db)
        except TelegramError as exc:
            raise _error(422, "telegram_error", str(exc))
        report.pop("bot_id", None)
        if not get_settings().bot_token:
            raise _error(422, "telegram_not_configured", "Set BOT_TOKEN and TELEGRAM_CHANNEL_ID, then try again.")
        return report

    @api.post("/integrations/telegram/invite-links", status_code=201)
    def invite_link(body: InviteLinkIn, user: User = Depends(require_role(*MUTATING_ROLES)), db: Session = Depends(get_db)):
        campaign = _get_campaign(db, body.campaign_id)
        try:
            link = create_campaign_invite(db, campaign.id)
            db.commit()
        except TelegramError as exc:
            db.rollback()
            raise _error(422, "telegram_error", str(exc))
        return {"id": link.id, "campaign_id": campaign.id, "name": link.link_name, "invite_link": link.invite_link}

    @api.post("/webhooks/telegram")
    async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
        settings = get_settings()
        supplied = request.headers.get("x-telegram-bot-api-secret-token", "")
        if not settings.telegram_webhook_secret or not _secret_ok(supplied, settings.telegram_webhook_secret):
            raise _error(401, "invalid_webhook_secret", "Webhook secret is missing or incorrect")
        try:
            payload = await request.json()
        except Exception:
            raise _error(422, "invalid_json", "Webhook body must be JSON")
        if not isinstance(payload, dict) or "update_id" not in payload:
            raise _error(422, "invalid_update", "A Telegram update_id is required")
        api_client = None
        if settings.bot_token:
            from app.services.telegram_api import TelegramAPI

            api_client = TelegramAPI()
        try:
            return ingest_update(db, payload, api_client)
        except TelegramError as exc:
            if exc.permanent:
                return {"status": "failed"}
            raise _error(503, "telegram_retry", "Telegram is temporarily unavailable")

    def _filters(request: Request) -> dict:
        allowed = ("from", "to", "campaign_id", "provider", "source", "consent_status", "campaign_status", "segment")
        return {key: request.query_params.get(key) for key in allowed if request.query_params.get(key)}

    @api.get("/analytics/overview")
    def analytics_overview(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
        payload = overview(db, _filters(request))
        payload["distribution"] = status_distribution(db)
        payload["providers"] = provider_performance(db)
        return payload

    @api.get("/analytics/funnel")
    def analytics_funnel(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
        return funnel(db, _filters(request))

    @api.get("/analytics/campaigns")
    def analytics_campaigns(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
        return campaign_comparison(db, _filters(request))

    @api.get("/analytics/membership")
    def analytics_membership(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
        return membership_series(db, _filters(request))

    @api.get("/analytics/retention")
    def analytics_retention(user: User = Depends(current_user), db: Session = Depends(get_db)):
        return retention(db)

    @api.get("/jobs")
    def list_jobs(user: User = Depends(require_role("super_admin", "campaign_manager")), db: Session = Depends(get_db)):
        rows = db.scalars(select(JobRun).order_by(JobRun.created_at.desc()).limit(50)).all()
        return {
            "items": [
                {"id": row.id, "task_name": row.task_name, "status": row.status, "progress": row.progress, "entity_id": row.entity_id, "error": row.error, "attempts": row.attempts, "started_at": _iso(row.started_at), "finished_at": _iso(row.finished_at)}
                for row in rows
            ]
        }

    @api.get("/audit-logs")
    def audit_logs(user: User = Depends(require_role("super_admin", "campaign_manager")), db: Session = Depends(get_db), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100)):
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
        total = int(db.scalar(select(func.count()).select_from(AuditLog)) or 0)
        rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
        return {
            "items": [
                {"id": row.id, "at": _iso(row.created_at), "actor_id": row.actor_id, "action": row.action, "entity_type": row.entity_type, "entity_id": row.entity_id, "metadata": row.metadata_json, "ip_address": row.ip_address}
                for row in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    @api.get("/settings/consent-policy")
    def get_policy(user: User = Depends(current_user), db: Session = Depends(get_db)):
        return _policy(db)

    @api.put("/settings/consent-policy")
    def put_policy(body: PolicyIn, request: Request, user: User = Depends(require_role("super_admin")), db: Session = Depends(get_db)):
        _upsert_setting(db, "consent_policy", body.model_dump())
        _upsert_setting(db, "retention_days", {"days": body.retention_days})
        write_audit(db, action="settings.consent_policy", entity_type="system_settings", entity_id=None, actor_id=user.id, ip_address=client_ip(request))
        db.commit()
        return _policy(db)


def _policy(db: Session) -> dict:
    row = db.get(SystemSetting, "consent_policy")
    value = row.value if row else {}
    return {
        "policy_version": value.get("policy_version", "1"),
        "retention_days": value.get("retention_days"),
        "frequency_cap_days": value.get("frequency_cap_days", get_settings().frequency_cap_days),
        "default_region": value.get("default_region", get_settings().default_region),
    }


def _upsert_setting(db: Session, key: str, value: dict) -> None:
    row = db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value
        row.updated_at = utcnow()


def _batch_out(batch: ImportBatch) -> dict:
    return {
        "id": batch.id,
        "filename": batch.filename,
        "status": batch.status,
        "total_rows": batch.total_rows,
        "processed_rows": batch.processed_rows,
        "valid_rows": batch.valid_rows,
        "invalid_rows": batch.invalid_rows,
        "duplicate_rows": batch.duplicate_rows,
        "inserted_rows": batch.inserted_rows,
        "error_summary": batch.error_summary,
        "created_at": _iso(batch.created_at),
        "completed_at": _iso(batch.completed_at),
    }


def _consent_out(consent: Consent) -> dict:
    return {
        "id": consent.id,
        "contact_id": consent.contact_id,
        "channel": consent.channel,
        "purpose": consent.purpose,
        "status": consent.status,
        "source": consent.source,
        "policy_version": consent.policy_version,
        "evidence_ref": consent.evidence_ref,
        "created_at": _iso(consent.created_at),
        "withdrawn_at": _iso(consent.withdrawn_at),
        "expires_at": _iso(consent.expires_at),
    }


def _secret_ok(supplied: str, expected: str) -> bool:
    if not supplied or not expected or len(supplied) != len(expected):
        return False
    return secrets.compare_digest(supplied, expected)


def _csv_safe(value) -> str:
    text = "" if value is None else str(value)
    if text[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + text
    return text


def _validate_campaign_body(body: CampaignIn) -> None:
    if body.outreach_channel not in CHANNELS:
        raise _error(422, "invalid_channel", "Unknown outreach channel")
    try:
        validate_template(body.message_template or "")
    except CampaignError as exc:
        raise _error(422, exc.code, str(exc))
    if body.start_at and body.end_at and body.end_at < body.start_at:
        raise _error(422, "invalid_dates", "The end date must be after the start date")


register(router, get_db)
