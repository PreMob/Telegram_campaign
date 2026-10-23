"""Idempotent jobs. Permanent permission and suppression outcomes are not retried."""

from __future__ import annotations

import logging

from app.database import SessionLocal, init_engine
from app.logging_config import configure_logging
from app.models import JobRun, utcnow
from app.security import redact
from app.services.providers import TransientProviderError
from app.services.telegram_api import TelegramError
from app.workers.celery_app import celery

log = logging.getLogger(__name__)
configure_logging()


def _session():
    init_engine()
    return SessionLocal()


def _job(db, name: str, entity_id: str) -> JobRun:
    job = JobRun(task_name=name, entity_type=name, entity_id=entity_id, status="running", started_at=utcnow(), attempts=1)
    db.add(job)
    db.commit()
    return job


def run_import(batch_id: str) -> None:
    from app.services.imports import process_import

    db = _session()
    job = _job(db, "import", batch_id)
    try:
        process_import(db, batch_id)
        job.status = "completed"
        job.progress = 100
        job.finished_at = utcnow()
        db.commit()
    except Exception as exc:
        job.status = "failed"
        job.error = redact(str(exc))[:500]
        job.finished_at = utcnow()
        db.commit()
        raise
    finally:
        db.close()


def run_dispatch(campaign_id: str) -> None:
    from app.services.campaigns import dispatch_campaign

    db = _session()
    job = _job(db, "dispatch", campaign_id)
    try:
        dispatch_campaign(db, campaign_id)
        job.status = "completed"
        job.progress = 100
        job.finished_at = utcnow()
        db.commit()
    except TransientProviderError as exc:
        job.status = "retry"
        job.error = redact(str(exc))[:500]
        db.commit()
        raise
    except TelegramError as exc:
        job.status = "failed" if exc.permanent else "retry"
        job.error = redact(str(exc))[:500]
        job.finished_at = utcnow() if exc.permanent else None
        db.commit()
        if not exc.permanent:
            raise
    except Exception as exc:
        job.status = "failed"
        job.error = redact(str(exc))[:500]
        job.finished_at = utcnow()
        db.commit()
        raise
    finally:
        db.close()


def run_reconcile() -> dict:
    from app.services.telegram_service import reconcile_linked_members

    db = _session()
    try:
        return reconcile_linked_members(db)
    finally:
        db.close()


def run_promote() -> int:
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.models import Campaign, CampaignStatus
    from app.services.jobs import enqueue_dispatch

    db = _session()
    try:
        now = datetime.now(timezone.utc)
        rows = list(db.scalars(select(Campaign).where(Campaign.status == CampaignStatus.scheduled.value)))
        promoted = 0
        for campaign in rows:
            start = campaign.start_at
            if start is None:
                continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if start <= now:
                enqueue_dispatch(campaign.id)
                promoted += 1
        return promoted
    finally:
        db.close()


def run_retention() -> int:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.models import Contact, SystemSetting
    from app.services.state import refresh_contact_state

    db = _session()
    try:
        setting = db.get(SystemSetting, "retention_days")
        days = (setting.value or {}).get("days") if setting else None
        if not days:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
        contacts = list(db.scalars(select(Contact).where(Contact.created_at < cutoff, Contact.erased_at.is_(None))))
        for contact in contacts:
            _erase(db, contact)
            refresh_contact_state(db, contact)
        db.commit()
        return len(contacts)
    finally:
        db.close()


def _erase(db, contact) -> None:
    import secrets

    from app.security import encrypt_phone, phone_hmac

    tombstone = f"+0{secrets.token_hex(8)}"
    contact.phone_ciphertext = encrypt_phone("erased")
    contact.phone_hmac = phone_hmac(tombstone)
    contact.phone_last4 = ""
    contact.name = None
    contact.communication_preferences = {}
    contact.erased_at = __import__("app.models", fromlist=["utcnow"]).utcnow()


def run_analytics_snapshot() -> None:
    from app.models import SystemSetting
    from app.services.analytics import overview

    db = _session()
    try:
        payload = overview(db, {})
        row = db.get(SystemSetting, "analytics_snapshot")
        if row is None:
            db.add(SystemSetting(key="analytics_snapshot", value={"cards": payload["cards"]}))
        else:
            row.value = {"cards": payload["cards"]}
        db.commit()
    finally:
        db.close()


@celery.task(name="app.workers.tasks.process_import_task", bind=True, max_retries=2)
def process_import_task(self, batch_id: str):
    try:
        run_import(batch_id)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=min(60, 2 ** self.request.retries))


@celery.task(name="app.workers.tasks.dispatch_campaign_task", bind=True, max_retries=3)
def dispatch_campaign_task(self, campaign_id: str):
    try:
        run_dispatch(campaign_id)
    except (TransientProviderError, TelegramError) as exc:
        if isinstance(exc, TelegramError) and exc.permanent:
            return
        raise self.retry(exc=exc, countdown=min(120, 2 ** self.request.retries))


@celery.task(name="app.workers.tasks.reconcile_membership_task", bind=True, max_retries=3)
def reconcile_membership_task(self):
    try:
        run_reconcile()
    except TelegramError as exc:
        if exc.permanent:
            return
        raise self.retry(exc=exc, countdown=min(300, 2 ** self.request.retries))


@celery.task(name="app.workers.tasks.promote_scheduled_task")
def promote_scheduled_task():
    run_promote()


@celery.task(name="app.workers.tasks.retention_task")
def retention_task():
    run_retention()


@celery.task(name="app.workers.tasks.analytics_snapshot_task")
def analytics_snapshot_task():
    run_analytics_snapshot()
