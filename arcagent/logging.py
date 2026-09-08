"""Structured logging with field level PII redaction.

Rules this module enforces, from AGENTS.md:
  - phone numbers, emails and names never reach a log sink in the clear
  - transcript text is never logged at INFO

Use ``get_logger(__name__)`` everywhere instead of ``logging.getLogger``.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sys
from typing import Any

import structlog

# Matches +14155550123, (415) 555-0123, 415-555-0123, 4155550123.
PHONE_RE = re.compile(r"(?:\+?\d{1,2}[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b")
EMAIL_RE = re.compile(r"\b[\w.%+\-]+@[\w.\-]+\.[A-Za-z]{2,}\b")

# Values under these keys are masked rather than pattern scrubbed, because a
# name or a raw transcript has no reliable pattern.
NAME_KEYS = frozenset({"name", "caller_name", "first_name", "last_name", "employer_name"})
NUMBER_KEYS = frozenset({"callback_number", "from_number", "to_number", "coordinator_number"})
TRANSCRIPT_KEYS = frozenset({"text", "transcript", "utterance", "next_utterance"})


def hash_number(number: str) -> str:
    """Stable non reversible id for a phone number, safe to store and log."""
    if not number:
        return ""
    return hashlib.sha256(number.encode("utf-8")).hexdigest()[:16]


def mask_name(name: str | None) -> str:
    """``Maria Gonzalez`` becomes ``M. G.``. Enough to correlate, not to identify."""
    if not name:
        return ""
    return " ".join(f"{part[0]}." for part in name.split() if part)


def mask_number(number: str | None) -> str:
    """``+14155550123`` becomes ``***0123``."""
    if not number:
        return ""
    digits = re.sub(r"\D", "", number)
    return f"***{digits[-4:]}" if len(digits) >= 4 else "***"


def redact_text(value: str) -> str:
    """Scrub phone numbers and emails out of free text."""
    value = EMAIL_RE.sub("[email]", value)
    return PHONE_RE.sub("[phone]", value)


def _redact(value: Any, key: str | None = None) -> Any:
    if key in NAME_KEYS and isinstance(value, str):
        return mask_name(value)
    if key in NUMBER_KEYS and isinstance(value, str):
        return mask_number(value)
    if key in TRANSCRIPT_KEYS and isinstance(value, str):
        return f"<{len(value)} chars redacted>"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_redact(v, key) for v in value)
    return value


def redact_processor(_logger: Any, _method: str, event_dict: dict) -> dict:
    """structlog processor applying redaction to every value in the event."""
    return {k: _redact(v, k) for k, v in event_dict.items()}


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    """Install the structlog pipeline. Idempotent, safe to call more than once."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    renderer = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
