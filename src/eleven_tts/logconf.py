"""Structured logging setup using only the standard library.

`setup_logging(json=True)` emits one JSON object per line — easy to ship to a log
aggregator. `json=False` gives a readable console format for local runs. Either
way, log records can carry structured `extra={...}` fields.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

# Attributes present on every LogRecord; anything else was passed via `extra=`.
_RESERVED = set(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Render a LogRecord as a single-line JSON object including extra fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: int | str = logging.INFO, *, json: bool = False) -> None:
    """Configure the root logger once. Safe to call multiple times."""
    handler = logging.StreamHandler(stream=sys.stderr)
    if json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s")
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str = "eleven_tts") -> logging.Logger:
    return logging.getLogger(name)
