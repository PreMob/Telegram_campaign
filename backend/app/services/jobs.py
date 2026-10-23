"""Enqueue background work. Celery is used when Redis is configured; tests run inline."""

from __future__ import annotations

import logging
import threading

from app.config import get_settings

log = logging.getLogger(__name__)


def enqueue_import(batch_id: str) -> None:
    _enqueue("app.workers.tasks.process_import_task", batch_id)


def enqueue_dispatch(campaign_id: str) -> None:
    _enqueue("app.workers.tasks.dispatch_campaign_task", campaign_id)


def _enqueue(task_name: str, entity_id: str) -> None:
    mode = get_settings().resolved_task_mode
    if mode == "inline":
        _run(task_name, entity_id)
        return
    if mode == "celery":
        from app.workers.celery_app import celery

        celery.send_task(task_name, args=[entity_id])
        return
    thread = threading.Thread(target=_run, args=(task_name, entity_id), daemon=True)
    thread.start()


def _run(task_name: str, entity_id: str) -> None:
    if task_name.endswith("process_import_task"):
        from app.workers.tasks import run_import

        run_import(entity_id)
    elif task_name.endswith("dispatch_campaign_task"):
        from app.workers.tasks import run_dispatch

        run_dispatch(entity_id)
    else:
        log.warning("unknown task %s", task_name)
