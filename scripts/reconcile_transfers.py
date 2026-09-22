"""Queue old unresolved transfers for coordinator review. Dry-run by default.

    python -m scripts.reconcile_transfers
    python -m scripts.reconcile_transfers --older-than-minutes 60 --limit 100 --apply

No vendor calls or redials occur. Schedule externally with monitoring once the
operator chooses a cutoff suitable for the longest expected live conversation.
"""

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import SQLAlchemyError

from arcagent.persistence.db import session_scope
from arcagent.telephony.transfer_state import reconcile_stale, stale_transfer_candidates


def reconcile(
    *,
    older_than_minutes: int = 60,
    limit: int = 100,
    apply: bool = False,
    database_url: str | None = None,
    now: datetime | None = None,
) -> dict:
    if type(older_than_minutes) is not int or not 1 <= older_than_minutes <= 10_080:
        raise ValueError("Age must be between one minute and one week")
    cutoff = (now or datetime.now(UTC)) - timedelta(minutes=older_than_minutes)
    with session_scope(database_url) as session:
        count = (
            reconcile_stale(session, cutoff, limit=limit)
            if apply
            else len(stale_transfer_candidates(session, cutoff, limit=limit))
        )
    return {
        "mode": "applied" if apply else "dry_run",
        "recoveries": count,
        "older_than_minutes": older_than_minutes,
        "limit": limit,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--older-than-minutes", type=int, default=60)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        summary = reconcile(
            older_than_minutes=args.older_than_minutes, limit=args.limit, apply=args.apply
        )
    except ValueError as exc:
        parser.error(str(exc))
    except SQLAlchemyError:
        print(
            "Transfer reconciliation failed: database unavailable; no success acknowledged.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
