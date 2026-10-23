"""Phone normalization. A valid number is not evidence of a Telegram account."""

from __future__ import annotations

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat


def normalize_phone(raw: str, default_region: str = "US") -> tuple[str | None, str | None]:
    text = (raw or "").strip()
    if not text:
        return None, "Phone number is empty"
    if text.startswith("=") or text.startswith("+=") or "\x00" in text:
        text = text.replace("\x00", "")
    try:
        parsed = phonenumbers.parse(text, default_region or None)
    except NumberParseException:
        return None, "Phone number could not be parsed"
    if not phonenumbers.is_valid_number(parsed):
        return None, "Phone number is not valid for the detected region"
    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164), None


def sanitize_text(value: str | None, limit: int = 200) -> str | None:
    if value is None:
        return None
    cleaned = str(value).replace("\x00", "").strip()
    if not cleaned:
        return None
    return cleaned[:limit]
