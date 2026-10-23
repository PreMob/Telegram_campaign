import os

os.environ["ENVIRONMENT"] = "test"
os.environ["TASK_MODE"] = "inline"
os.environ["APP_SECRET_KEY"] = "test-app-secret-key-with-32-characters"
os.environ["PHONE_ENCRYPTION_KEY"] = "test-phone-encryption-key"
os.environ["PHONE_HMAC_KEY"] = "test-phone-hmac-key"
os.environ["DATABASE_URL"] = "sqlite+pysqlite://"
os.environ["REDIS_URL"] = ""
os.environ["BOT_TOKEN"] = ""
os.environ["TELEGRAM_CHANNEL_ID"] = ""
os.environ["TELEGRAM_WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["LOGIN_RATE_LIMIT"] = "30"
os.environ["DATA_DIR"] = "./data"
os.environ["SEED_DEMO"] = "false"

import pytest
from sqlalchemy import select

from app.bootstrap import seed_roles
from app.config import get_settings
from app.database import Base, SessionLocal, init_engine
from app.models import Role, User
from app.rate_limit import reset as reset_rate_limit
from app.security import hash_password


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    init_engine("sqlite+pysqlite://", force=True)
    from app import models  # noqa: F401

    Base.metadata.drop_all(init_engine())
    Base.metadata.create_all(init_engine())
    db = SessionLocal()
    seed_roles(db)
    db.commit()
    db.close()
    reset_rate_limit()
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
    from app.services.telegram_api import set_telegram_client

    set_telegram_client(None)
    reset_rate_limit()


@pytest.fixture()
def auth(client):
    email, password, headers = create_user()
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    csrf = client.cookies.get("tagp_csrf")
    return {"X-CSRF-Token": csrf, "email": email, "password": password, "role": "super_admin"}


def create_user(role: str = "super_admin", email: str = "admin@example.com", password: str = "Str0ng-password") -> tuple[str, str, dict]:
    db = SessionLocal()
    seed_roles(db)
    role_row = db.scalar(select(Role).where(Role.name == role))
    existing = db.scalar(select(User).where(User.email == email))
    if existing is None:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                full_name="Test User",
                role_id=role_row.id,
            )
        )
        db.commit()
    db.close()
    return email, password, {}
