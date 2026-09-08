"""Delete transcripts past the retention window.

    python -m scripts.purge_old_data --dry-run
    python -m scripts.purge_old_data

Turns carry the conversation and are deleted. The lead record survives: that is the business
record the practice is entitled to keep, and the conversation that produced it is not.

This is a script, not a managed job. A production deployment schedules it and alerts when it
does not run, which is noted as a gap in docs/compliance_design.md.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from arcagent.config import get_settings
from arcagent.logging import configure_logging, get_logger
from arcagent.persistence.db import session_scope
from arcagent.persistence.models import Call, Turn

log = get_logger(__name__)


def cutoff(days: int, now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) - timedelta(days=days)


def purge(days: int, dry_run: bool = False, database_url: str | None = None) -> dict[str, int]:
    """Delete turns for calls older than the window. Returns what was, or would be, removed."""
    before = cutoff(days)
    with session_scope(database_url) as session:
        stale_call_ids = list(session.scalars(select(Call.id).where(Call.started_at < before)))
        turn_count = (
            session.scalar(
                select(func.count()).select_from(Turn).where(Turn.call_id.in_(stale_call_ids))
            )
            or 0
            if stale_call_ids
            else 0
        )
        if not dry_run and stale_call_ids:
            session.execute(delete(Turn).where(Turn.call_id.in_(stale_call_ids)))
        return {"calls": len(stale_call_ids), "turns": turn_count}


def main() -> None:
    configure_logging(level="INFO")
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Purge transcripts past the retention window.")
    parser.add_argument("--days", type=int, default=settings.transcript_retention_days)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    counts = purge(days=args.days, dry_run=args.dry_run)
    verb = "would delete" if args.dry_run else "deleted"
    print(
        f"{verb} {counts['turns']} turns across {counts['calls']} calls older than {args.days} days"
    )


if __name__ == "__main__":
    main()
