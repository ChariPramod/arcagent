"""Transactional transfer state. Callers must commit before external side effects.

Only a verified webhook adapter may supply normalized terminal evidence. Database
exceptions intentionally propagate: the caller must return a retryable failure,
never acknowledge an event whose state was not committed. No vendor calls or logs.
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from arcagent.persistence.models import Call, Outcome
from arcagent.persistence.transfer_models import TransferAttempt, TransferProgress
from arcagent.persistence.workflow_models import FollowupTask, WorkflowAudit

TERMINAL_OUTCOMES = frozenset({"completed", "no_answer", "busy", "failed", "canceled", "unbridged"})
REQUEST_STATUSES = frozenset({"accepted", "failed", "uncertain"})
ACTOR = "system:transfer"


class TransferStateError(ValueError):
    """Invalid or mismatched evidence; messages contain no submitted identifiers."""


def _call(session: Session, call_id: int) -> Call:
    call = session.scalar(
        select(Call)
        .where(Call.id == call_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if call is None:
        raise TransferStateError("Transfer call not found")
    return call


def _locked(session: Session, attempt_id: str) -> tuple[Call, TransferAttempt]:
    call_id = session.scalar(
        select(TransferAttempt.call_id).where(TransferAttempt.id == attempt_id)
    )
    if call_id is None:
        raise TransferStateError("Transfer attempt not found")
    call = _call(session, call_id)
    attempt = session.scalar(
        select(TransferAttempt)
        .where(TransferAttempt.id == attempt_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if attempt is None:
        raise TransferStateError("Transfer attempt not found")
    return call, attempt


def begin_transfer(session: Session, call_id: int) -> tuple[TransferAttempt, bool]:
    """One durable intent per call; only the creator may issue an external request.

    A pending intent may represent a crashed sender. It is deliberately not safe
    to resend: reconcile via verified evidence or coordinator follow-up instead.
    """
    call = _call(session, call_id)
    attempt = session.scalar(select(TransferAttempt).where(TransferAttempt.call_id == call_id))
    if attempt is not None:
        return attempt, False
    if call.outcome is not None:
        raise TransferStateError("Call already has a final outcome")
    attempt = TransferAttempt(id=str(uuid4()), call_id=call_id, request_status="pending")
    session.add(attempt)
    session.flush()
    return attempt, True


def _followup(session: Session, call: Call, attempt: TransferAttempt) -> None:
    task = session.scalar(
        select(FollowupTask).where(FollowupTask.call_id == call.id).with_for_update()
    )
    if task is None:
        task = FollowupTask(
            call_id=call.id, status="open", notes="", created_by=ACTOR, updated_by=ACTOR, revision=1
        )
        session.add(task)
        session.flush()
    existing = session.scalar(
        select(WorkflowAudit.id).where(
            WorkflowAudit.call_id == call.id,
            WorkflowAudit.action == "transfer_recovery",
            WorkflowAudit.actor == ACTOR,
        )
    )
    if existing is not None:
        return
    # Existing human assignment, notes and status are deliberately untouched.
    session.add(
        WorkflowAudit(
            call_id=call.id,
            entity="followup",
            entity_id=task.id,
            revision=task.revision,
            actor=ACTOR,
            action="transfer_recovery",
            changes={"attempt_id": attempt.id, "outcome": attempt.outcome},
        )
    )


def _finish(call: Call, now: datetime) -> None:
    # Observed terminal callback time; no claim this is vendor-measured duration.
    call.ended_at = now
    start = call.started_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    call.duration_s = max(0.0, (now - start).total_seconds())


def mark_request(session: Session, attempt_id: str, status: str) -> TransferAttempt:
    """Persist HTTP request disposition, never treating acceptance as connection."""
    if status not in REQUEST_STATUSES:
        raise TransferStateError("Unsupported request status")
    call, attempt = _locked(session, attempt_id)
    if attempt.outcome is not None or attempt.request_status != "pending":
        return attempt
    attempt.request_status = status
    attempt.updated_at = datetime.now(UTC)
    if status == "failed":
        attempt.outcome = "failed"
        attempt.resolved_at = attempt.updated_at
        call.outcome = Outcome.ABANDONED
        _finish(call, attempt.updated_at)
        _followup(session, call, attempt)
    elif status == "uncertain":
        # A timeout may have applied the vendor update. Leave terminal outcome
        # unresolved so later verified completion can still reconcile it.
        _followup(session, call, attempt)
    session.flush()
    return attempt


def record_outcome(
    session: Session,
    attempt_id: str,
    *,
    parent_call_sid: str,
    child_call_sid: str,
    outcome: str,
    connection_confirmed: bool = False,
) -> TransferAttempt:
    """Apply verified evidence once; first terminal outcome wins conflicting replays.

    `completed` alone is insufficient. The adapter must separately establish
    connection evidence (for example the dial action's answered/completed semantics).
    """
    if outcome not in TERMINAL_OUTCOMES:
        raise TransferStateError("Unsupported transfer outcome")
    if not child_call_sid or len(child_call_sid) > 64:
        raise TransferStateError("Missing or invalid child call identity")
    if outcome == "completed" and connection_confirmed is not True:
        raise TransferStateError("Completion requires confirmed connection evidence")
    call, attempt = _locked(session, attempt_id)
    if call.twilio_call_sid != parent_call_sid or child_call_sid == parent_call_sid:
        raise TransferStateError("Transfer identity mismatch")
    if attempt.child_call_sid is not None and attempt.child_call_sid != child_call_sid:
        raise TransferStateError("Transfer child identity mismatch")
    if attempt.outcome is not None:
        return attempt
    attempt.child_call_sid = child_call_sid
    attempt.outcome = outcome
    attempt.updated_at = datetime.now(UTC)
    attempt.resolved_at = attempt.updated_at
    _finish(call, attempt.updated_at)
    if outcome == "completed":
        call.outcome = Outcome.HANDOFF
    else:
        call.outcome = Outcome.ABANDONED
        _followup(session, call, attempt)
    session.flush()
    return attempt


PROGRESS_STATUSES = frozenset(
    {"initiated", "ringing", "in-progress", "completed", "busy", "no-answer", "failed", "canceled"}
)


def record_progress(
    session: Session,
    attempt_id: str,
    *,
    parent_call_sid: str,
    child_call_sid: str,
    sequence: int,
    status: str,
) -> TransferAttempt:
    """Persist child events without confusing answered child with a bridged parent.

    Sequence numbers deduplicate transport retries. Old events remain available for
    audit and may establish terminal failure, but cannot overwrite terminal state.
    """
    if status not in PROGRESS_STATUSES or type(sequence) is not int or sequence < 0:
        raise TransferStateError("Invalid transfer progress")
    if not child_call_sid or len(child_call_sid) > 64:
        raise TransferStateError("Missing or invalid child call identity")
    call, attempt = _locked(session, attempt_id)
    if parent_call_sid != call.twilio_call_sid or child_call_sid == parent_call_sid:
        raise TransferStateError("Transfer identity mismatch")
    if attempt.child_call_sid is not None and attempt.child_call_sid != child_call_sid:
        raise TransferStateError("Transfer child identity mismatch")
    prior = session.scalar(
        select(TransferProgress).where(
            TransferProgress.attempt_id == attempt_id, TransferProgress.sequence == sequence
        )
    )
    if prior is not None:
        if prior.status != status:
            raise TransferStateError("Conflicting transfer progress replay")
        return attempt
    attempt.child_call_sid = child_call_sid
    session.add(TransferProgress(attempt_id=attempt_id, sequence=sequence, status=status))
    if status in {"busy", "no-answer", "failed", "canceled"}:
        record_outcome(
            session,
            attempt_id,
            parent_call_sid=parent_call_sid,
            child_call_sid=child_call_sid,
            outcome=status.replace("-", "_"),
        )
    session.flush()
    return attempt


def reconcile_stale(session: Session, cutoff: datetime, *, limit: int = 100) -> int:
    """Queue unresolved old transfers for human review; never redial or infer failure.

    Returns number of newly created recovery audit entries, so repeated sweeps are
    idempotent. Caller owns transaction, scheduling and a suitably conservative cutoff.
    """
    identifiers = stale_transfer_candidates(session, cutoff, limit=limit)
    created = 0
    for identifier in identifiers:
        call, attempt = _locked(session, identifier)
        if attempt.outcome is not None:
            continue
        before = session.scalar(
            select(WorkflowAudit.id).where(
                WorkflowAudit.call_id == call.id,
                WorkflowAudit.action == "transfer_recovery",
                WorkflowAudit.actor == ACTOR,
            )
        )
        _followup(session, call, attempt)
        created += before is None
    session.flush()
    return created


def stale_transfer_candidates(session: Session, cutoff: datetime, *, limit: int = 100) -> list[str]:
    """Read-only bounded candidate scan shared by dry-run and apply."""
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise TransferStateError("Invalid reconciliation batch size")
    if cutoff.tzinfo is None:
        raise TransferStateError("Reconciliation cutoff must be timezone aware")
    return list(
        session.scalars(
            select(TransferAttempt.id)
            .where(
                TransferAttempt.outcome.is_(None),
                TransferAttempt.created_at < cutoff,
                ~select(WorkflowAudit.id)
                .where(
                    WorkflowAudit.call_id == TransferAttempt.call_id,
                    WorkflowAudit.action == "transfer_recovery",
                    WorkflowAudit.actor == ACTOR,
                )
                .exists(),
            )
            .order_by(TransferAttempt.created_at, TransferAttempt.id)
            .limit(limit)
        ).all()
    )
