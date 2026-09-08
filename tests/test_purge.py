"""Retention purge: transcripts go, the business record stays."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from arcagent.persistence.db import get_engine, get_session_factory
from arcagent.persistence.models import Base, Call, Lead, Speaker, Turn
from arcagent.persistence.repo import CallRepository
from scripts.purge_old_data import cutoff, purge


def _seed(url: str, ages_days: list[int]) -> None:
    Base.metadata.create_all(get_engine(url))
    session = get_session_factory(url)()
    try:
        repo = CallRepository(session)
        for index, age in enumerate(ages_days):
            call = repo.start_call(f"CA_{index}", "+14155550123")
            call.started_at = datetime.now(UTC) - timedelta(days=age)
            repo.add_turn(call.id, 0, Speaker.CALLER, "i need a full arch")
            repo.add_turn(call.id, 1, Speaker.AGENT, "understood")
            repo.save_lead(call.id, {"name": "Bob", "treatment_interest": "full_arch"})
        session.commit()
    finally:
        session.close()


def test_the_cutoff_is_the_retention_window_ago() -> None:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    assert cutoff(30, now) == datetime(2026, 8, 31, tzinfo=UTC)


def test_old_transcripts_go_and_recent_ones_stay(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'purge.db'}"
    _seed(url, ages_days=[45, 40, 5])

    counts = purge(days=30, database_url=url)
    assert counts["calls"] == 2
    assert counts["turns"] == 4

    session = get_session_factory(url)()
    try:
        assert session.query(Turn).count() == 2  # only the recent call's turns
    finally:
        session.close()


def test_the_lead_record_survives_the_purge(tmp_path: Path) -> None:
    """The conversation is deleted. The business record the practice may keep is not."""
    url = f"sqlite:///{tmp_path / 'purge_leads.db'}"
    _seed(url, ages_days=[90])

    purge(days=30, database_url=url)
    session = get_session_factory(url)()
    try:
        assert session.query(Turn).count() == 0
        assert session.query(Lead).count() == 1
        assert session.query(Call).count() == 1
    finally:
        session.close()


def test_a_dry_run_deletes_nothing(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'purge_dry.db'}"
    _seed(url, ages_days=[90])

    counts = purge(days=30, dry_run=True, database_url=url)
    assert counts["turns"] == 2

    session = get_session_factory(url)()
    try:
        assert session.query(Turn).count() == 2
    finally:
        session.close()


def test_nothing_to_purge_is_not_an_error(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'purge_empty.db'}"
    Base.metadata.create_all(get_engine(url))
    assert purge(days=30, database_url=url) == {"calls": 0, "turns": 0}
