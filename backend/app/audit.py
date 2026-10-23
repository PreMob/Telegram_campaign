"""Append-only audit records. Metadata must stay free of secrets and raw phone numbers."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AuditLog


def write_audit(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    actor_id: str | None = None,
    metadata: dict | None = None,
    ip_address: str | None = None,
) -> None:
    safe = {}
    for key, value in (metadata or {}).items():
        lowered = key.lower()
        if any(part in lowered for part in ("password", "token", "secret", "phone", "authorization")):
            continue
        safe[key] = value
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=safe,
            ip_address=ip_address,
        )
    )
