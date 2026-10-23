"""Environment-based configuration. Production secrets are never given defaults."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"
    database_url: str = "sqlite+pysqlite:///./data/dev.db"
    redis_url: str = ""
    bot_token: str = ""
    telegram_channel_id: str = ""
    telegram_webhook_secret: str = ""
    app_secret_key: str = ""
    admin_user_id: str = ""
    admin_email: str = ""
    admin_password: str = ""
    phone_encryption_key: str = ""
    phone_hmac_key: str = ""
    task_mode: str = ""
    session_hours: int = 12
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    default_region: str = "US"
    seed_demo: bool = False
    data_dir: str = "./data"
    login_rate_limit: int = 10
    login_rate_window_seconds: int = 60
    auto_create_schema: bool = True

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    sms_api_url: str = ""
    sms_api_token: str = ""
    whatsapp_api_url: str = ""
    whatsapp_api_token: str = ""

    frequency_cap_days: int = Field(default=7)

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def is_test(self) -> bool:
        return self.environment.lower() == "test"

    @property
    def resolved_task_mode(self) -> str:
        if self.task_mode:
            return self.task_mode
        if self.redis_url:
            return "celery"
        return "thread"

    @property
    def telegram_configured(self) -> bool:
        return bool(self.bot_token and self.telegram_channel_id)

    def production_errors(self) -> list[str]:
        if not self.is_production:
            return []
        missing = []
        required = {
            "DATABASE_URL": self.database_url,
            "APP_SECRET_KEY": self.app_secret_key,
            "PHONE_ENCRYPTION_KEY": self.phone_encryption_key,
            "PHONE_HMAC_KEY": self.phone_hmac_key,
            "TELEGRAM_WEBHOOK_SECRET": self.telegram_webhook_secret,
        }
        for name, value in required.items():
            if not value or value.lower().startswith("change-me") or "replace" in value.lower():
                missing.append(name)
        if self.database_url.startswith("sqlite"):
            missing.append("DATABASE_URL must be PostgreSQL in production")
        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()
