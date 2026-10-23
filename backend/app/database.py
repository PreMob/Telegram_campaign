"""SQLAlchemy engine and session. SQLite is for tests and local lightweight mode."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

engine = None
SessionLocal = sessionmaker(autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _enable_sqlite_fk(dbapi_connection, _connection_record) -> None:
    module = getattr(dbapi_connection.__class__, "__module__", "")
    if module.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def init_engine(url: str | None = None, force: bool = False):
    global engine, SessionLocal
    if engine is not None and not force:
        return engine
    from app.config import get_settings

    settings = get_settings()
    db_url = url or settings.database_url
    connect_args: dict = {}
    poolclass = None
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if db_url in {"sqlite://", "sqlite+pysqlite://", "sqlite:///:memory:", "sqlite+pysqlite:///:memory:"}:
            db_url = "sqlite+pysqlite://"
            poolclass = StaticPool
    kwargs = {"pool_pre_ping": True, "connect_args": connect_args, "future": True}
    if poolclass is not None:
        kwargs["poolclass"] = poolclass
    engine = create_engine(db_url, **kwargs)
    event.listen(engine, "connect", _enable_sqlite_fk)
    SessionLocal.configure(bind=engine)
    return engine


def get_db():
    if engine is None:
        init_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
