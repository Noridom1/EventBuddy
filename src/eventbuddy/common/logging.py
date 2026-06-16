import json
import logging
import sys

from eventbuddy.config import settings

# Structured fields the agent trace (Impl 10) attaches via `log.info(event, extra={...})`.
# Anything in this set found on a LogRecord is merged into the JSON line; every other
# record stays `{level, logger, msg}` exactly as before (back-compat).
_TRACE_FIELDS = (
    "event", "thread_id", "step", "scope", "role", "event_id", "seeded",
    "tool", "usage", "payload",
)


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {"level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        for field in _TRACE_FIELDS:
            if field in record.__dict__:
                entry[field] = record.__dict__[field]
        return json.dumps(entry, default=str)


def configure_logging() -> None:
    """Configure root logging. Call ONCE at application startup."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
