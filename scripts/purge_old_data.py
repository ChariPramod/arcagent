"""Preview or redact expired transcript text in bounded, resumable batches.

    python -m scripts.purge_old_data
    python -m scripts.purge_old_data --apply --batch-size 500 --max-batches 10

Only nonempty turn text for completed calls older than the retention window is cleared.
Turn rows and latency evidence remain, as do all business, audit and delivery records.
This does not erase backups, extracted lead fields, evaluation fixtures or vendor data.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from arcagent.config import get_settings
from arcagent.persistence.db import session_scope
from arcagent.persistence.models import Call, Turn
from arcagent.persistence.retention import bounded_integer, candidates, cutoff, limit_statement_time


def purge(
    days: int,
    dry_run: bool = True,
    database_url: str | None = None,
    *,
    batch_size: int = 500,
    max_batches: int = 10,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Preview by default. Explicit dry_run=False clears content, never rows.

    Each batch commits independently. On failure earlier batches may have committed;
    retrying is safe because marked turns no longer qualify. One invocation processes
    at most batch_size * max_batches candidate turns and never loads transcript text.
    """
    current = now or datetime.now(UTC)
    before = cutoff(days, current)
    bounded_integer(batch_size, "batch_size", 1000)
    bounded_integer(max_batches, "max_batches", 100)
    if type(dry_run) is not bool:
        raise ValueError("dry_run must be a boolean")
    cursor = 0
    call_ids: set[int] = set()
    turns = 0
    batches = 0
    for _ in range(max_batches):
        with session_scope(database_url) as session:
            limit_statement_time(session)
            records = session.execute(candidates(before, after_id=cursor).limit(batch_size)).all()
            if not records:
                break
            cursor = records[-1].id
            batches += 1
            if dry_run:
                processed = records
            else:
                # Recheck eligibility in the write. A concurrent worker that already
                # redacted these turns is not counted twice.
                processed = session.execute(
                    update(Turn)
                    .where(
                        Turn.id.in_([row.id for row in records]),
                        Turn.transcript_redacted_at.is_(None),
                        Turn.text != "",
                        Turn.call_id.in_(select(Call.id).where(Call.ended_at < before)),
                    )
                    .values(text="", transcript_redacted_at=current)
                    .returning(Turn.id, Turn.call_id)
                    .execution_options(synchronize_session=False)
                ).all()
            turns += len(processed)
            call_ids.update(row.call_id for row in processed)
    with session_scope(database_url) as session:
        limit_statement_time(session)
        # Applied batches are excluded by their marker. For previews, continue after
        # the last selected ID so has_more describes work beyond this run's budget.
        has_more = (
            session.execute(candidates(before, after_id=cursor if dry_run else 0).limit(1)).first()
            is not None
        )
    return {
        "calls": len(call_ids),
        "turns": turns,
        "batches": batches,
        "has_more": has_more,
        "dry_run": dry_run,
        "before": before.isoformat(),
        "retention_days": days,
    }


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Preview or redact expired transcript text.")
    parser.add_argument("--days", type=int, default=settings.transcript_retention_days)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply", action="store_true", help="Clear eligible text; preserves turn rows."
    )
    mode.add_argument("--dry-run", action="store_true", help="Preview only (the default).")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--max-batches", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        counts = purge(
            days=args.days,
            dry_run=not args.apply,
            database_url=settings.database_url,
            batch_size=args.batch_size,
            max_batches=args.max_batches,
        )
    except ValueError as exc:
        parser.error(str(exc))
    except SQLAlchemyError:
        print(
            "Retention stopped: database unavailable or query budget exceeded. "
            "Earlier batches may have committed; rerunning is safe.",
            file=sys.stderr,
        )
        return 1
    verb = "redacted" if args.apply else "would redact"
    print(
        f"{verb} text from {counts['turns']} turns across {counts['calls']} completed calls; "
        "turn rows and metrics are retained."
    )
    if counts["has_more"]:
        print(
            "More eligible content remains beyond this batch budget. Review and rerun explicitly."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
