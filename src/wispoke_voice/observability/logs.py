"""
Structured JSON logging.

One line per log event, machine-parseable. We add `extra` fields directly to
the JSON record so Langfuse/Datadog ingestion (Phase 3) doesn't need a custom
parser — the keys are stable and queryable.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


_RESERVED_LOG_KEYS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        # Surface any `extra={...}` fields the caller passed.
        for k, v in record.__dict__.items():
            if k in _RESERVED_LOG_KEYS or k.startswith("_"):
                continue
            payload[k] = v

        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger once at process startup."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())

    root = logging.getLogger()
    # Replace existing handlers so re-running setup (e.g. in tests) doesn't
    # double-log.
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # LiveKit's own loggers are quite chatty at DEBUG — keep them at INFO
    # unless the user explicitly opted into DEBUG.
    if level.upper() != "DEBUG":
        logging.getLogger("livekit").setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
