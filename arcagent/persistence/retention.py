"""Bounded transcript-content retention, independent of business record retention."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, select, text
from sqlalchemy.orm import Session

from arcagent.persistence.models import Call, Turn


def bounded_integer(value: int, name: str, maximum: int) -> None:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer between 1 and {maximum}")


def cutoff(days: int, now: datetime | None = None) -> datetime:
    bounded_integer(days, "days", 36_500)
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must have a timezone")
    return current.astimezone(UTC) - timedelta(days=days)


def candidates(before: datetime, *, after_id: int = 0) -> Select:
    """Project identifiers and character lengths only, never transcript content."""
    return (
        select(Turn.id, Turn.call_id, func.length(Turn.text).label("characters"))
        .join(Call, Call.id == Turn.call_id)
        .where(
            Call.ended_at < before,
            Turn.id > after_id,
            Turn.transcript_redacted_at.is_(None),
            Turn.text != "",
        )
        .order_by(Turn.id)
    )


def limit_statement_time(session: Session) -> None:
    """Bound database work on deployed Postgres without a persistent session setting."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SET LOCAL statement_timeout = '3s'"))
        session.execute(text("SET LOCAL lock_timeout = '1s'"))


def retention_preview(
    session: Session, *, days: int, limit: int = 1000, now: datetime | None = None
) -> dict[str, Any]:
    bounded_integer(limit, "limit", 1000)
    current = now or datetime.now(UTC)
    before = cutoff(days, current)
    limit_statement_time(session)
    records = session.execute(candidates(before).limit(limit + 1)).all()
    selected = records[:limit]
    return {
        "checked_at": current.astimezone(UTC).isoformat(),
        "retention_days": days,
        "before": before.isoformat(),
        "scope": "completed_call_turn_text",
        "preview_limit": limit,
        "candidate_turns": len(selected),
        "candidate_calls": len({row.call_id for row in selected}),
        "candidate_text_characters": sum(row.characters for row in selected),
        "has_more": len(records) > limit,
    }
