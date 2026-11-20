"""Structured logging with secret redaction."""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

from config import get_settings

_SECRET_PATTERNS = [
    re.compile(r"(api[_-]?key|token|secret|password)([\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9_\-]{6,})", re.I),
]


def redact(text: str) -> str:
    """Best effort redaction so keys never reach logs."""
    if not text:
        return text
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}***redacted***", text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        return redact(super().format(record))


_configured = False


def configure_logging(level: int | None = None) -> logging.Logger:
    global _configured
    logger = logging.getLogger("consul")
    if _configured:
        return logger

    logger.setLevel(level or (logging.DEBUG if os.environ.get("CONSUL_DEBUG") else logging.INFO))
    logger.propagate = False
    fmt = RedactingFormatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    try:
        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(Path(settings.data_dir) / "consul.log", encoding="utf-8")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except Exception:  # pragma: no cover - logging must never break the app
        pass

    _configured = True
    return logger


def get_logger(name: str = "consul") -> logging.Logger:
    configure_logging()
    return logging.getLogger(name if name.startswith("consul") else f"consul.{name}")
