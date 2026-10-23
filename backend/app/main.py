"""FastAPI application."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import database
from app.api.routes import _secret_ok, router
from app.bootstrap import seed_admin, seed_demo, seed_roles
from app.config import get_settings
from app.database import Base, SessionLocal, init_engine
from app.logging_config import configure_logging
from app.security import redact

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_EXEMPT = {"/api/v1/auth/login", "/api/v1/webhooks/telegram", "/health", "/api/v1/health"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    problems = settings.production_errors()
    if problems:
        raise RuntimeError("Refusing to start: " + ", ".join(problems))
    if not settings.is_test:
        if not settings.app_secret_key or not settings.phone_encryption_key or not settings.phone_hmac_key:
            raise RuntimeError(
                "Set APP_SECRET_KEY, PHONE_ENCRYPTION_KEY, and PHONE_HMAC_KEY in the environment before starting."
            )
        Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
        (Path(settings.data_dir) / "uploads").mkdir(parents=True, exist_ok=True)
        init_engine()
        if settings.auto_create_schema and database.engine is not None:
            Base.metadata.create_all(database.engine)
        db = SessionLocal()
        try:
            seed_roles(db)
            if settings.admin_email and settings.admin_password:
                seed_admin(db, settings.admin_email, settings.admin_password)
            if settings.seed_demo:
                seed_demo(db)
            db.commit()
        finally:
            db.close()
    yield


app = FastAPI(title="Telegram Audience Growth Platform", version="1.0.0", lifespan=lifespan)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def protect(request: Request, call_next):
    if request.method not in SAFE_METHODS and request.url.path not in CSRF_EXEMPT:
        cookie = request.cookies.get("tagp_csrf", "")
        header = request.headers.get("x-csrf-token", "")
        if not _secret_ok(header, cookie):
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "csrf", "message": "CSRF token missing or invalid"}},
            )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        payload = {"error": exc.detail}
    else:
        payload = {"error": {"code": "error", "message": redact(str(exc.detail))}}
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.get("/health")
@app.get("/api/v1/health")
def health():
    settings = get_settings()
    database = "ok"
    try:
        init_engine()
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
    except Exception:
        database = "error"
    redis_state = "unconfigured"
    if settings.redis_url:
        try:
            import redis

            redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1).ping()
            redis_state = "ok"
        except Exception:
            redis_state = "error"
    status = "ok" if database == "ok" and redis_state in {"ok", "unconfigured"} else "degraded"
    return {
        "status": status,
        "database": database,
        "redis": redis_state,
        "environment": settings.environment,
        "telegram_configured": settings.telegram_configured,
        "task_mode": settings.resolved_task_mode,
    }


app.include_router(router)
