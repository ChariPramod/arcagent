"""CLI recovery is dry-run by default and bounded when explicitly applied."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from arcagent.persistence.db import get_engine, session_scope
from arcagent.persistence.models import Base, Call
from arcagent.persistence.workflow_models import FollowupTask
from arcagent.telephony.transfer_state import begin_transfer
from scripts import reconcile_transfers


def test_dry_run_is_read_only_and_apply_is_bounded_idempotent(tmp_path):
    url = f"sqlite:///{tmp_path / 'recovery.db'}"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with session_scope(url) as session:
        for index in range(3):
            call = Call(twilio_call_sid=f"parent{index}", from_number_hash="hash")
            session.add(call)
            session.flush()
            attempt, _ = begin_transfer(session, call.id)
            attempt.created_at = now - timedelta(hours=2)
    assert reconcile_transfers.reconcile(database_url=url, now=now, limit=2) == {
        "mode": "dry_run",
        "recoveries": 2,
        "older_than_minutes": 60,
        "limit": 2,
    }
    with session_scope(url) as session:
        assert session.scalar(select(func.count()).select_from(FollowupTask)) == 0
    assert (
        reconcile_transfers.reconcile(database_url=url, now=now, limit=2, apply=True)["recoveries"]
        == 2
    )
    assert (
        reconcile_transfers.reconcile(database_url=url, now=now, limit=2, apply=True)["recoveries"]
        == 1
    )
    assert (
        reconcile_transfers.reconcile(database_url=url, now=now, limit=2, apply=True)["recoveries"]
        == 0
    )
    with session_scope(url) as session:
        assert all(call.outcome is None for call in session.scalars(select(Call)))
        assert session.scalar(select(func.count()).select_from(FollowupTask)) == 3
    engine.dispose()


def test_cli_requires_apply_flag_and_sanitizes_database_failure(monkeypatch, capsys):
    observed = []

    def fake(**kwargs):
        observed.append(kwargs)
        return {"mode": "dry_run", "recoveries": 0}

    monkeypatch.setattr(reconcile_transfers, "reconcile", fake)
    assert reconcile_transfers.main([]) == 0
    assert observed[0]["apply"] is False
    assert reconcile_transfers.main(["--apply"]) == 0
    assert observed[1]["apply"] is True

    def unavailable(**kwargs):
        raise OperationalError("secret-database-url", {}, Exception("private-details"))

    monkeypatch.setattr(reconcile_transfers, "reconcile", unavailable)
    assert reconcile_transfers.main(["--apply"]) == 1
    output = capsys.readouterr()
    assert "database unavailable" in output.err
    assert "secret" not in output.err
    assert "private" not in output.err


@pytest.mark.parametrize("age", [0, -1, 10081])
def test_invalid_age_fails_before_database(age):
    with pytest.raises(ValueError):
        reconcile_transfers.reconcile(older_than_minutes=age)
