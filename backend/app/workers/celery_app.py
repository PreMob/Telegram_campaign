"""Celery application. Imported by the worker process, not by request handlers."""

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()
celery = Celery(
    "tagp",
    broker=settings.redis_url or "memory://",
    backend=settings.redis_url or None,
    include=["app.workers.tasks"],
)
celery.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    beat_schedule={
        "reconcile-membership": {
            "task": "app.workers.tasks.reconcile_membership_task",
            "schedule": crontab(minute=15),
        },
        "promote-scheduled": {
            "task": "app.workers.tasks.promote_scheduled_task",
            "schedule": crontab(minute="*"),
        },
        "retention-sweep": {
            "task": "app.workers.tasks.retention_task",
            "schedule": crontab(hour=3, minute=0),
        },
        "analytics-snapshot": {
            "task": "app.workers.tasks.analytics_snapshot_task",
            "schedule": crontab(minute="*/15"),
        },
    },
)
