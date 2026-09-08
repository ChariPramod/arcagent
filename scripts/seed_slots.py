"""Seed callback slots.

    python -m scripts.seed_slots                 # two weeks of weekday slots
    python -m scripts.seed_slots --weeks 4 --clear

Weekdays only, 9 to 5, on the hour, in the configured local timezone. Existing slots are
left alone unless --clear is passed, so running this twice does not double book anything.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from arcagent.persistence.db import session_scope
from arcagent.persistence.models import Slot

FIRST_HOUR = 9
LAST_HOUR = 17  # exclusive: the last slot starts at 16:00
SLOT_MINUTES = 30


def slot_times(start: datetime, weeks: int) -> list[datetime]:
    """Weekday slots on the hour between FIRST_HOUR and LAST_HOUR."""
    slots: list[datetime] = []
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    for offset in range(weeks * 7):
        current = day + timedelta(days=offset)
        if current.weekday() >= 5:  # saturday, sunday
            continue
        for hour in range(FIRST_HOUR, LAST_HOUR):
            moment = current.replace(hour=hour)
            if moment > start:
                slots.append(moment)
    return slots


def seed(weeks: int = 2, clear: bool = False, now: datetime | None = None) -> int:
    """Insert missing slots. Returns how many were created."""
    now = now or datetime.now(UTC)
    created = 0
    with session_scope() as session:
        if clear:
            session.execute(delete(Slot).where(Slot.booked.is_(False)))
        existing = {
            row for row in session.scalars(select(Slot.slot_start).where(Slot.slot_start > now))
        }
        for start in slot_times(now, weeks):
            if start in existing:
                continue
            session.add(
                Slot(
                    slot_start=start,
                    slot_end=start + timedelta(minutes=SLOT_MINUTES),
                    booked=False,
                )
            )
            created += 1
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed callback slots.")
    parser.add_argument("--weeks", type=int, default=2)
    parser.add_argument("--clear", action="store_true", help="remove unbooked slots first")
    args = parser.parse_args()
    print(f"created {seed(weeks=args.weeks, clear=args.clear)} slots")


if __name__ == "__main__":
    main()
