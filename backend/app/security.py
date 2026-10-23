"""Password hashing, sessions, phone encryption, and redaction."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import get_settings

SENSITIVE_MARKERS = ("bot_token", "password", "authorization", "secret", "cookie", "phone")


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 64:
        raise ValueError("Password must be between 12 and 64 characters")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _require_secret(value: str, name: str) -> str:
    settings = get_settings()
    if value:
        return value
    if settings.is_production or settings.is_test:
        raise RuntimeError(f"{name} is required")
    raise RuntimeError(
        f"{name} is missing. Copy .env.example to .env and set a unique secret before starting the app."
    )


def _fernet(secret: str) -> Fernet:
    raw = secret.encode("utf-8")
    try:
        return Fernet(raw)
    except (ValueError, InvalidToken):
        derived = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"tagp-phone-v1",
            info=b"phone-encryption",
        ).derive(raw)
        return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_phone(phone_e164: str) -> str:
    secret = _require_secret(get_settings().phone_encryption_key, "PHONE_ENCRYPTION_KEY")
    return _fernet(secret).encrypt(phone_e164.encode("utf-8")).decode("utf-8")


def decrypt_phone(ciphertext: str) -> str:
    secret = _require_secret(get_settings().phone_encryption_key, "PHONE_ENCRYPTION_KEY")
    return _fernet(secret).decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def phone_hmac(phone_e164: str) -> str:
    secret = _require_secret(get_settings().phone_hmac_key, "PHONE_HMAC_KEY")
    return hmac.new(secret.encode("utf-8"), phone_e164.encode("utf-8"), hashlib.sha256).hexdigest()


def hash_token(token: str) -> str:
    secret = _require_secret(get_settings().app_secret_key, "APP_SECRET_KEY")
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def mask_phone(phone_e164: str) -> str:
    digits = phone_e164
    if len(digits) <= 4:
        return "****"
    return f"{digits[:2]}{'*' * max(len(digits) - 6, 2)}{digits[-4:]}"


def new_csrf() -> str:
    return secrets.token_urlsafe(32)


def create_session_token(user_id: str, role: str, csrf: str) -> str:
    settings = get_settings()
    secret = _require_secret(settings.app_secret_key, "APP_SECRET_KEY")
    exp = datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)
    return jwt.encode(
        {"sub": user_id, "role": role, "csrf": csrf, "exp": exp},
        secret,
        algorithm="HS256",
    )


def decode_session_token(token: str) -> dict:
    secret = _require_secret(get_settings().app_secret_key, "APP_SECRET_KEY")
    return jwt.decode(token, secret, algorithms=["HS256"])


def redact(text: str) -> str:
    settings = get_settings()
    redacted = text
    for secret in (settings.bot_token, settings.app_secret_key, settings.phone_encryption_key, settings.phone_hmac_key):
        if secret and len(secret) > 6 and secret in redacted:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


def can_view_phone(role: str) -> bool:
    return role in {"super_admin", "campaign_manager"}


def can_export(role: str) -> bool:
    return role in {"super_admin", "campaign_manager"}


def can_mutate_contacts(role: str) -> bool:
    return role in {"super_admin", "campaign_manager"}


def can_manage_campaigns(role: str) -> bool:
    return role in {"super_admin", "campaign_manager"}


def can_approve(role: str) -> bool:
    return role in {"super_admin", "campaign_manager"}


def can_manage_users(role: str) -> bool:
    return role == "super_admin"


def can_launch(role: str) -> bool:
    return role in {"super_admin", "campaign_manager"}
