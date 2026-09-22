"""Request acceptance, verified completion, recovery and atomic rollback."""

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from arcagent.persistence.models import Base, Call, Outcome
from arcagent.persistence.transfer_models import TransferAttempt
from arcagent.persistence.workflow_models import FollowupTask, WorkflowAudit
from arcagent.telephony.transfer_state import (
    TransferStateError,
    begin_transfer,
    mark_request,
    record_outcome,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        call = Call(twilio_call_sid="parent", from_number_hash="hash")
        session.add(call)
        session.commit()
        yield session, call
    engine.dispose()


def result(session, attempt, outcome="completed", child="child", confirmed=True):
    return record_outcome(
        session,
        attempt.id,
        parent_call_sid="parent",
        child_call_sid=child,
        outcome=outcome,
        connection_confirmed=confirmed,
    )


def test_begin_and_acceptance_never_claim_connection(db):
    session, call = db
    attempt, created = begin_transfer(session, call.id)
    assert created
    assert begin_transfer(session, call.id) == (attempt, False)
    mark_request(session, attempt.id, "accepted")
    session.commit()
    assert call.outcome is None
    assert attempt.outcome is None
    assert attempt.request_status == "accepted"
    assert session.scalar(select(func.count()).select_from(TransferAttempt)) == 1


def test_confirmed_completion_can_arrive_before_request_response(db):
    session, call = db
    attempt, _ = begin_transfer(session, call.id)
    result(session, attempt)
    mark_request(session, attempt.id, "failed")
    session.commit()
    assert call.outcome == Outcome.HANDOFF
    assert attempt.outcome == "completed"
    assert session.scalar(select(func.count()).select_from(FollowupTask)) == 0


@pytest.mark.parametrize("outcome", ["no_answer", "busy", "failed", "canceled"])
def test_failure_creates_one_recovery_and_terminal_never_regresses(db, outcome):
    session, call = db
    attempt, _ = begin_transfer(session, call.id)
    result(session, attempt, outcome)
    result(session, attempt, outcome)
    result(session, attempt, "completed")
    session.commit()
    assert attempt.outcome == outcome
    assert call.outcome == Outcome.ABANDONED
    assert session.scalar(select(func.count()).select_from(FollowupTask)) == 1
    assert session.scalar(select(func.count()).select_from(WorkflowAudit)) == 1


def test_failure_preserves_existing_human_work(db):
    session, call = db
    task = FollowupTask(
        call_id=call.id,
        notes="Manual note",
        assignee="coordinator",
        status="done",
        revision=7,
        created_by="human",
        updated_by="human",
    )
    session.add(task)
    session.commit()
    attempt, _ = begin_transfer(session, call.id)
    mark_request(session, attempt.id, "uncertain")
    result(session, attempt, "busy")
    session.commit()
    assert (task.notes, task.assignee, task.status, task.revision) == (
        "Manual note",
        "coordinator",
        "done",
        7,
    )
    assert session.scalar(select(func.count()).select_from(WorkflowAudit)) == 1


def test_uncertain_request_can_later_be_confirmed(db):
    session, call = db
    attempt, _ = begin_transfer(session, call.id)
    mark_request(session, attempt.id, "uncertain")
    assert call.outcome is None
    assert attempt.outcome is None
    result(session, attempt)
    session.commit()
    assert call.outcome == Outcome.HANDOFF


def test_unproven_completion_and_identity_mismatches_rejected(db):
    session, call = db
    attempt, _ = begin_transfer(session, call.id)
    with pytest.raises(TransferStateError, match="confirmed"):
        result(session, attempt, confirmed=False)
    with pytest.raises(TransferStateError, match="identity"):
        record_outcome(
            session, attempt.id, parent_call_sid="wrong", child_call_sid="child", outcome="busy"
        )
    assert call.outcome is None
    result(session, attempt)
    with pytest.raises(TransferStateError, match="child identity"):
        result(session, attempt, child="different")


def test_recovery_and_outcome_roll_back_together(db):
    session, call = db
    attempt, _ = begin_transfer(session, call.id)
    session.commit()
    result(session, attempt, "busy")
    session.rollback()
    assert session.get(TransferAttempt, attempt.id).outcome is None
    assert session.get(Call, call.id).outcome is None
    assert session.scalar(select(func.count()).select_from(FollowupTask)) == 0
    assert session.scalar(select(func.count()).select_from(WorkflowAudit)) == 0


def test_failed_request_is_terminal_and_not_resent(db):
    session, call = db
    attempt, _ = begin_transfer(session, call.id)
    mark_request(session, attempt.id, "failed")
    mark_request(session, attempt.id, "accepted")
    session.commit()
    assert begin_transfer(session, call.id) == (attempt, False)
    assert attempt.request_status == "failed"
    assert call.outcome == Outcome.ABANDONED


def test_migration_upgrade_and_downgrade(tmp_path):
    from alembic.config import Config
    from sqlalchemy import inspect

    from alembic import command

    url = f"sqlite:///{tmp_path / 'migration.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    assert "transfer_attempts" in inspect(engine).get_table_names()
    command.downgrade(config, "c21ab845df10")
    assert "transfer_attempts" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    assert "transfer_attempts" in inspect(engine).get_table_names()
    engine.dispose()


def test_progress_completed_is_not_proof_of_bridge_and_deduplicates(db):
    from arcagent.persistence.transfer_models import TransferProgress
    from arcagent.telephony.transfer_state import record_progress

    session, call = db
    attempt, _ = begin_transfer(session, call.id)
    for status, sequence in [("completed", 3), ("ringing", 1), ("completed", 3)]:
        record_progress(
            session,
            attempt.id,
            parent_call_sid="parent",
            child_call_sid="child",
            sequence=sequence,
            status=status,
        )
    session.commit()
    assert call.outcome is None
    assert attempt.outcome is None
    assert session.scalar(select(func.count()).select_from(TransferProgress)) == 2
    with pytest.raises(TransferStateError, match="Conflicting"):
        record_progress(
            session,
            attempt.id,
            parent_call_sid="parent",
            child_call_sid="child",
            sequence=3,
            status="busy",
        )
    result(session, attempt)
    assert call.outcome == Outcome.HANDOFF


def test_progress_failure_binds_child_and_preserves_terminal(db):
    from arcagent.telephony.transfer_state import record_progress

    session, call = db
    attempt, _ = begin_transfer(session, call.id)
    record_progress(
        session,
        attempt.id,
        parent_call_sid="parent",
        child_call_sid="child",
        sequence=2,
        status="no-answer",
    )
    record_progress(
        session,
        attempt.id,
        parent_call_sid="parent",
        child_call_sid="child",
        sequence=0,
        status="initiated",
    )
    assert attempt.outcome == "no_answer"
    assert call.outcome == Outcome.ABANDONED
    with pytest.raises(TransferStateError, match="child identity"):
        result(session, attempt, child="other")


def test_stale_reconciliation_idempotent_without_inventing_outcome(db):
    from datetime import UTC, datetime, timedelta

    from arcagent.telephony.transfer_state import reconcile_stale

    session, call = db
    attempt, _ = begin_transfer(session, call.id)
    attempt.created_at = datetime.now(UTC) - timedelta(hours=1)
    session.commit()
    cutoff = datetime.now(UTC) - timedelta(minutes=20)
    assert reconcile_stale(session, cutoff) == 1
    assert reconcile_stale(session, cutoff) == 0
    assert call.outcome is None
    assert attempt.outcome is None
    assert begin_transfer(session, call.id)[1] is False
    result(session, attempt)
    session.commit()
    assert reconcile_stale(session, cutoff) == 0
    assert call.outcome == Outcome.HANDOFF


def test_failure_to_persist_child_identity_rolls_back_call_and_followup(db):
    from sqlalchemy.exc import IntegrityError

    session, call = db
    attempt, _ = begin_transfer(session, call.id)
    result(session, attempt)
    other = Call(twilio_call_sid="other_parent", from_number_hash="hash")
    session.add(other)
    session.flush()
    other_attempt, _ = begin_transfer(session, other.id)
    session.commit()
    with pytest.raises(IntegrityError):
        record_outcome(
            session,
            other_attempt.id,
            parent_call_sid="other_parent",
            child_call_sid="child",
            outcome="busy",
        )
    session.rollback()
    assert session.get(Call, other.id).outcome is None
    assert session.get(TransferAttempt, other_attempt.id).outcome is None
    assert session.scalar(select(func.count()).select_from(FollowupTask)) == 0


def test_unbridged_completion_recovers_and_terminal_time_is_stable(db):
    session, call = db
    attempt, _ = begin_transfer(session, call.id)
    result(session, attempt, "unbridged", confirmed=False)
    ended_at = call.ended_at
    assert ended_at is not None
    assert call.duration_s is not None and call.duration_s >= 0
    assert call.outcome == Outcome.ABANDONED
    assert session.scalar(select(func.count()).select_from(FollowupTask)) == 1
    result(session, attempt, "completed")
    assert call.ended_at.replace(tzinfo=None) == ended_at.replace(tzinfo=None)
    assert call.outcome == Outcome.ABANDONED
