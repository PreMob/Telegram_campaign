"""JSON logs with secret redaction."""

import json
import logging
from datetime import datetime, timezone

from app.security import redact


class RedactingJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=True)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingJsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for name in ("httpx", "telegram", "celery"):
        logging.getLogger(name).setLevel(logging.WARNING)
