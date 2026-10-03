"""Retention removes expired conversation content, preserving operational evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from arcagent.persistence.db import get_engine, session_scope
from arcagent.persistence.models import Base, Call, Lead, Speaker, Turn
from scripts.purge_old_data import cutoff, purge

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


def _seed(url: str, ages_days: list[int], *, completed: bool = True) -> None:
    Base.metadata.create_all(get_engine(url))
    with session_scope(url) as session:
        for index, age in enumerate(ages_days):
            ended = NOW - timedelta(days=age)
            call = Call(
                twilio_call_sid=f"CA_{index}",
                from_number_hash="fixture-hash",
                started_at=ended - timedelta(minutes=5),
                ended_at=ended if completed else None,
            )
            session.add(call)
            session.flush()
            session.add(Lead(call_id=call.id, name="private-contact"))
            session.add_all(
                [
                    Turn(
                        call_id=call.id,
                        turn_index=0,
                        speaker=Speaker.CALLER,
                        text="private request",
                        stt_final_ms=250,
                    ),
                    Turn(
                        call_id=call.id,
                        turn_index=1,
                        speaker=Speaker.AGENT,
                        text="private reply",
                        llm_ttft_ms=125,
                        interrupted=True,
                    ),
                ]
            )


def test_the_cutoff_is_the_retention_window_ago() -> None:
    assert cutoff(30, NOW) == NOW - timedelta(days=30)


@pytest.mark.parametrize("days", [0, -1, 36501, True])
def test_invalid_retention_never_reaches_database(days: int) -> None:
    with pytest.raises(ValueError, match="days"):
        purge(days=days, database_url="invalid", now=NOW)


def test_dry_run_is_the_default_and_does_not_load_conversation_content(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'preview.db'}"
    _seed(url, [90])
    result = purge(days=30, database_url=url, now=NOW)
    assert result["dry_run"] is True
    assert result["turns"] == 2
    assert result["calls"] == 1
    assert result["has_more"] is False
    with session_scope(url) as session:
        assert session.scalar(select(func.count(Turn.id)).where(Turn.text != "")) == 2
        assert (
            session.scalar(
                select(func.count(Turn.id)).where(Turn.transcript_redacted_at.is_not(None))
            )
            == 0
        )


def test_apply_redacts_only_old_completed_content_and_preserves_latency(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'purge.db'}"
    _seed(url, [45, 40, 5])
    result = purge(days=30, dry_run=False, database_url=url, now=NOW)
    assert result["calls"] == 2
    assert result["turns"] == 4
    with session_scope(url) as session:
        turns = session.scalars(select(Turn).order_by(Turn.id)).all()
        assert len(turns) == 6
        assert [turn.text for turn in turns[:4]] == [""] * 4
        assert all(turn.transcript_redacted_at is not None for turn in turns[:4])
        assert turns[4].text == "private request"
        assert turns[0].stt_final_ms == 250
        assert turns[1].llm_ttft_ms == 125
        assert turns[1].interrupted is True
        assert session.scalar(select(func.count(Call.id))) == 3
        assert session.scalar(select(func.count(Lead.id))) == 3
    repeated = purge(days=30, dry_run=False, database_url=url, now=NOW)
    assert repeated["turns"] == 0


def test_unfinished_calls_and_exact_cutoff_are_never_redacted(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'active.db'}"
    _seed(url, [90, 30])
    with session_scope(url) as session:
        session.get(Call, 1).ended_at = None
    assert purge(days=30, dry_run=False, database_url=url, now=NOW)["turns"] == 0


@pytest.mark.parametrize("dry_run", [False, True])
def test_batch_budget_bounds_work_and_supports_safe_resume(tmp_path: Path, dry_run: bool) -> None:
    url = f"sqlite:///{tmp_path / 'bounded.db'}"
    _seed(url, [90, 80, 70])
    result = purge(days=30, dry_run=dry_run, database_url=url, now=NOW, batch_size=2, max_batches=2)
    assert result["turns"] == 4
    assert result["calls"] == 2
    assert result["batches"] == 2
    assert result["has_more"] is True
    if not dry_run:
        result = purge(
            days=30, dry_run=False, database_url=url, now=NOW, batch_size=2, max_batches=2
        )
        assert result["turns"] == 2
        assert result["has_more"] is False


@pytest.mark.parametrize(
    "options",
    [
        {"batch_size": 0},
        {"batch_size": 1001},
        {"max_batches": 0},
        {"max_batches": 101},
    ],
)
def test_invalid_batch_budget_never_reaches_database(options: dict) -> None:
    with pytest.raises(ValueError):
        purge(days=30, database_url="invalid", **options)


def test_cli_requires_explicit_apply_for_writes(monkeypatch, capsys) -> None:
    from arcagent.config import Settings
    from scripts import purge_old_data

    writes: list[bool] = []

    def run(**kwargs):
        writes.append(not kwargs["dry_run"])
        return {"turns": 0, "calls": 0, "batches": 0, "has_more": False}

    monkeypatch.setattr(purge_old_data, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(purge_old_data, "purge", run)
    assert purge_old_data.main([]) == 0
    assert purge_old_data.main(["--apply"]) == 0
    assert writes == [False, True]
    assert "redact" in capsys.readouterr().out


def test_content_redaction_preserves_business_audit_and_delivery_evidence(tmp_path: Path) -> None:
    from uuid import uuid4

    from arcagent.persistence.integration_models import IntegrationDelivery
    from arcagent.persistence.pipeline_models import Location
    from arcagent.persistence.workflow_models import WorkflowAudit

    url = f"sqlite:///{tmp_path / 'evidence.db'}"
    _seed(url, [90])
    with session_scope(url) as session:
        location = Location(name="Fixture location", timezone="UTC", updated_by="operator")
        session.add(location)
        session.flush()
        session.add(
            IntegrationDelivery(
                call_id=1,
                location_id=location.id,
                location_name=location.name,
                destination="automation",
                client_request_id=str(uuid4()),
                status="uncertain",
                attempt_count=1,
                payload={"contact": "private-contact"},
                config_fingerprint="fixture",
                created_by="operator",
                updated_by="operator",
            )
        )
        session.add(
            WorkflowAudit(
                call_id=1,
                entity="pipeline",
                entity_id=1,
                revision=1,
                actor="operator",
                action="updated",
                changes={"stage": "contacted"},
            )
        )
    purge(days=30, dry_run=False, database_url=url, now=NOW)
    with session_scope(url) as session:
        delivery = session.scalar(select(IntegrationDelivery))
        assert delivery.status == "uncertain"
        assert delivery.payload == {"contact": "private-contact"}
        assert delivery.attempt_count == 1
        assert session.scalar(select(WorkflowAudit)).changes == {"stage": "contacted"}
        assert session.scalar(select(Lead)).name == "private-contact"


def test_failure_after_committed_batch_can_be_resumed(tmp_path: Path, monkeypatch) -> None:
    from contextlib import contextmanager

    from sqlalchemy.exc import OperationalError

    from scripts import purge_old_data

    url = f"sqlite:///{tmp_path / 'resume.db'}"
    _seed(url, [90, 80])
    sessions = 0

    @contextmanager
    def interrupted_session(database_url):
        nonlocal sessions
        sessions += 1
        if sessions == 2:
            raise OperationalError("fixture", {}, Exception("fixture"))
        with session_scope(database_url) as session:
            yield session

    with monkeypatch.context() as patch:
        patch.setattr(purge_old_data, "session_scope", interrupted_session)
        with pytest.raises(OperationalError):
            purge(days=30, dry_run=False, database_url=url, now=NOW, batch_size=2)
    with session_scope(url) as session:
        assert session.scalar(select(func.count(Turn.id)).where(Turn.text == "")) == 2
    resumed = purge(days=30, dry_run=False, database_url=url, now=NOW, batch_size=2)
    assert resumed["turns"] == 2
    assert resumed["has_more"] is False


def test_cli_does_not_leak_database_errors_or_claim_completion(monkeypatch, capsys) -> None:
    from sqlalchemy.exc import OperationalError

    from scripts import purge_old_data

    def unavailable(**kwargs):
        raise OperationalError("private-query", {}, Exception("private-secret"))

    monkeypatch.setattr(purge_old_data, "purge", unavailable)
    assert purge_old_data.main(["--apply"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Earlier batches may have committed" in captured.err
    assert "private" not in captured.err
