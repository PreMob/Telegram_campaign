"""CSV and XLSX import. Contacts are never consented or un-suppressed by a file upload."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Consent, ConsentState, Contact, ImportBatch, ImportErrorRow, SuppressionRecord, utcnow
from app.phone import normalize_phone, sanitize_text
from app.security import encrypt_phone, phone_hmac
from app.services.state import refresh_contact_state

CHUNK = 500


def read_tabular(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        workbook = load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.active
        rows = list(sheet.iter_rows(values_only=True))
        workbook.close()
        if not rows:
            return [], []
        headers = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
        records = []
        for raw in rows[1:]:
            record = {}
            for index, header in enumerate(headers):
                if not header:
                    continue
                value = raw[index] if index < len(raw) else ""
                record[header] = "" if value is None else str(value)
            records.append(record)
        return headers, records
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = [header.strip() for header in (reader.fieldnames or [])]
    records = []
    for row in reader:
        records.append({(key or "").strip(): (value or "").strip() for key, value in row.items()})
    return headers, records


def preview_file(path: Path, limit: int = 8) -> dict:
    headers, records = read_tabular(path)
    return {"headers": headers, "preview": records[:limit], "row_count_estimate": len(records)}


def _mapped(row: dict, mapping: dict, field: str) -> str:
    column = mapping.get(field) or ""
    if not column:
        return ""
    return (row.get(column) or "").strip()


def process_import(db: Session, batch_id: str) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise ValueError("Import batch not found")
    if batch.status in {"completed", "cancelled"}:
        return batch
    batch.status = "running"
    db.commit()

    headers, records = read_tabular(Path(batch.storage_path))
    mapping = batch.column_mapping or {}
    if "phone" not in mapping:
        batch.status = "failed"
        batch.error_summary = "A phone column mapping is required"
        batch.completed_at = utcnow()
        db.commit()
        return batch

    batch.total_rows = len(records)
    seen_in_file: set[str] = set()
    pending_errors: list[ImportErrorRow] = []

    def flush_errors() -> None:
        if pending_errors:
            db.add_all(pending_errors)
            pending_errors.clear()

    for offset in range(0, len(records), CHUNK):
        db.refresh(batch)
        if batch.cancel_requested:
            batch.status = "cancelled"
            batch.completed_at = utcnow()
            flush_errors()
            db.commit()
            return batch
        chunk = records[offset : offset + CHUNK]
        for index, row in enumerate(chunk, start=offset + 2):
            phone_raw = _mapped(row, mapping, "phone")
            normalized, error = normalize_phone(phone_raw, batch.default_region)
            if error or not normalized:
                batch.invalid_rows += 1
                pending_errors.append(
                    ImportErrorRow(
                        batch_id=batch.id,
                        row_number=index,
                        field="phone",
                        raw_value=phone_raw[:120],
                        reason=error or "Invalid phone",
                    )
                )
                continue
            digest = phone_hmac(normalized)
            if digest in seen_in_file:
                batch.duplicate_rows += 1
                pending_errors.append(
                    ImportErrorRow(
                        batch_id=batch.id,
                        row_number=index,
                        field="phone",
                        raw_value=normalized[-4:].rjust(len(normalized), "*"),
                        reason="Duplicate within file",
                    )
                )
                continue
            seen_in_file.add(digest)
            existing = db.scalar(select(Contact).where(Contact.phone_hmac == digest))
            name = sanitize_text(_mapped(row, mapping, "name"))
            source = sanitize_text(_mapped(row, mapping, "source"), 120) or batch.default_source
            if existing is not None:
                batch.duplicate_rows += 1
                if existing.name is None and name and existing.erased_at is None:
                    existing.name = name
                # Suppression and withdrawn consent stay intact.
                if existing.suppression_status or db.scalar(
                    select(SuppressionRecord.id).where(
                        SuppressionRecord.contact_id == existing.id,
                        SuppressionRecord.active.is_(True),
                    )
                ):
                    refresh_contact_state(db, existing)
                pending_errors.append(
                    ImportErrorRow(
                        batch_id=batch.id,
                        row_number=index,
                        field="phone",
                        raw_value=f"***{normalized[-4:]}",
                        reason="Duplicate of an existing contact; consent and suppression were left unchanged",
                    )
                )
                continue

            contact = Contact(
                phone_ciphertext=encrypt_phone(normalized),
                phone_hmac=digest,
                phone_last4=normalized[-4:],
                name=name,
                source=source,
                import_batch_id=batch.id,
                consent_status=ConsentState.pending.value,
                is_demo=source == "demo_seed",
            )
            db.add(contact)
            db.flush()
            if batch.apply_consent_column:
                _apply_explicit_consent(db, batch, contact, row, mapping, index, pending_errors)
            refresh_contact_state(db, contact)
            batch.inserted_rows += 1
            batch.valid_rows += 1
        batch.processed_rows = min(offset + len(chunk), batch.total_rows)
        flush_errors()
        db.commit()

    batch.valid_rows = batch.inserted_rows
    batch.status = "completed"
    batch.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(batch)
    return batch


def _apply_explicit_consent(db, batch, contact, row, mapping, index, pending_errors) -> None:
    status_raw = _mapped(row, mapping, "consent_status").lower()
    if not status_raw:
        return
    if not batch.policy_version:
        pending_errors.append(
            ImportErrorRow(
                batch_id=batch.id,
                row_number=index,
                field="consent_status",
                raw_value=status_raw[:80],
                reason="Consent column ignored because no policy version was provided",
            )
        )
        return
    channel = _mapped(row, mapping, "consent_channel") or "telegram_invite"
    purpose = _mapped(row, mapping, "consent_purpose") or "channel_invitation"
    if status_raw in {"granted", "yes", "true"}:
        db.add(
            Consent(
                contact_id=contact.id,
                channel=channel,
                purpose=purpose,
                status=ConsentState.granted.value,
                source="import_column",
                policy_version=batch.policy_version,
            )
        )
    elif status_raw in {"withdrawn", "no", "false"}:
        db.add(
            Consent(
                contact_id=contact.id,
                channel=channel,
                purpose=purpose,
                status=ConsentState.withdrawn.value,
                source="import_column",
                policy_version=batch.policy_version,
                withdrawn_at=utcnow(),
            )
        )
        db.add(
            SuppressionRecord(
                contact_id=contact.id,
                reason="consent_withdrawn",
                source="import_column",
                active=True,
            )
        )
    else:
        pending_errors.append(
            ImportErrorRow(
                batch_id=batch.id,
                row_number=index,
                field="consent_status",
                raw_value=status_raw[:80],
                reason="Unrecognized consent value; contact left as consent pending",
            )
        )
