"""Read-only console views. Authentication runs before opening a database session."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import and_, case, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arcagent.config import Settings, get_settings
from arcagent.persistence.db import session_scope
from arcagent.persistence.models import Call, EvalResult, EvalRun, Lead, LeadScore, Outcome
from arcagent.persistence.repo import EvalRepository
from arcagent.persistence.transfer_models import TransferAttempt, TransferProgress
from evals import metrics
from evals.compare_runs import (
    NOISE_FLOOR,
    REGRESSION_GUARDS,
    InvalidComparison,
    _metrics_for,
    comparison_groups,
)
from evals.snapshots import saved_groups

bearer = HTTPBearer(auto_error=False)


def authenticate(
    response: Response,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    response.headers["Cache-Control"] = "no-store"
    if not settings.console_api_token:
        raise HTTPException(503, "Console access is not configured")
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), settings.console_api_token.encode()
    ):
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})


router = APIRouter(prefix="/api/console", dependencies=[Depends(authenticate)], tags=["console"])


def database() -> Iterator[Session]:
    try:
        with session_scope() as session:
            yield session
    except SQLAlchemyError as exc:
        raise HTTPException(503, "The workspace database is unavailable") from exc


Database = Annotated[Session, Depends(database)]


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat() if value.tzinfo is None else value.isoformat()


def call_summary(call: Call, lead: Lead | None, score: LeadScore | None) -> dict[str, Any]:
    return {
        "id": call.id,
        "name": lead.name if lead else None,
        "started_at": iso(call.started_at),
        "duration_s": call.duration_s,
        "outcome": call.outcome,
        "language": call.language,
        "treatment_interest": lead.treatment_interest if lead else None,
        "score": score.score if score else None,
        "threshold": score.threshold_used if score else None,
    }


@router.get("/calls")
def calls(
    session: Database,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    outcome: Outcome | None = None,
) -> dict[str, Any]:
    # Correlated latest-row lookups use parent/id indexes and never materialize
    # historical scores, clinical JSON or transcript text for a summary page.
    latest_lead = (
        select(Lead.id)
        .where(Lead.call_id == Call.id)
        .order_by(Lead.id.desc())
        .limit(1)
        .correlate(Call)
        .scalar_subquery()
    )
    latest_score = (
        select(LeadScore.id)
        .where(LeadScore.lead_id == Lead.id)
        .order_by(LeadScore.id.desc())
        .limit(1)
        .correlate(Lead)
        .scalar_subquery()
    )
    statement = (
        select(
            Call.id,
            Lead.name,
            Call.started_at,
            Call.duration_s,
            Call.outcome,
            Call.language,
            Lead.treatment_interest,
            LeadScore.score,
            LeadScore.threshold_used.label("threshold"),
        )
        .outerjoin(Lead, Lead.id == latest_lead)
        .outerjoin(LeadScore, LeadScore.id == latest_score)
    )
    count = select(func.count(Call.id))
    if outcome:
        statement = statement.where(Call.outcome == outcome)
        count = count.where(Call.outcome == outcome)
    records = session.execute(
        statement.order_by(Call.started_at.desc(), Call.id.desc()).offset(offset).limit(limit)
    ).mappings()
    return {
        "items": [{**row, "started_at": iso(row["started_at"])} for row in records],
        "total": session.scalar(count),
        "limit": limit,
        "offset": offset,
    }


def transfer_evidence(session: Session, call_id: int) -> dict[str, Any] | None:
    """Expose evidence without vendor identities or a claim of human verification."""
    attempt = session.scalar(select(TransferAttempt).where(TransferAttempt.call_id == call_id))
    if attempt is None:
        return None
    progress = session.scalar(
        select(TransferProgress)
        .where(TransferProgress.attempt_id == attempt.id)
        .order_by(TransferProgress.sequence.desc())
        .limit(1)
    )
    return {
        "request_status": attempt.request_status,
        "outcome": attempt.outcome,
        "connection_confirmed": attempt.outcome == "completed",
        "human_identity_verified": False,
        "created_at": iso(attempt.created_at),
        "updated_at": iso(attempt.updated_at),
        "resolved_at": iso(attempt.resolved_at),
        "latest_progress": (
            {
                "status": progress.status,
                "sequence": progress.sequence,
                "received_at": iso(progress.received_at),
            }
            if progress
            else None
        ),
        "timing_basis": "server_observed",
    }


@router.get("/calls/{call_id}")
def call_detail(
    call_id: Annotated[int, Path(gt=0, le=2_147_483_647)], session: Database
) -> dict[str, Any]:
    call = session.get(Call, call_id)
    if call is None:
        raise HTTPException(404, "Call not found")
    lead = session.scalar(
        select(Lead).where(Lead.call_id == call_id).order_by(Lead.id.desc()).limit(1)
    )
    score = (
        session.scalar(
            select(LeadScore)
            .where(LeadScore.lead_id == lead.id)
            .order_by(LeadScore.id.desc())
            .limit(1)
        )
        if lead
        else None
    )
    fields = (
        {
            name: getattr(lead, name)
            for name in (
                "treatment_interest",
                "missing_teeth_count",
                "pain_level",
                "considering_duration",
                "has_insurance",
                "employer_name",
                "plan_type",
                "coverage_awareness",
                "preferred_time",
                "callback_number",
                "financing_asked",
                "objections",
            )
        }
        if lead
        else {}
    )
    return {
        **call_summary(call, lead, score),
        "fields": fields,
        "transfer": transfer_evidence(session, call_id),
        "score_breakdown": score.score_breakdown if score else {},
        "decision": str(score.decision) if score else None,
        "turns": [
            {
                "id": turn.id,
                "speaker": str(turn.speaker),
                "text": turn.text,
                "transcript_redacted_at": iso(turn.transcript_redacted_at),
                "started_at": iso(turn.started_at),
                "node": turn.node_name,
                "interrupted": turn.interrupted,
                "latency": {
                    stage: getattr(turn, stage)
                    for stage in (
                        "stt_final_ms",
                        "llm_ttft_ms",
                        "tts_first_byte_ms",
                        "playback_start_ms",
                    )
                },
            }
            for turn in sorted(call.turns, key=lambda t: (t.turn_index, t.id))
        ],
    }


def run_summary(run: EvalRun) -> dict[str, Any]:
    rows = run.results
    passes: dict[str, list[bool]] = {}
    for row in rows:
        passes.setdefault(row.scenario_id, []).append(row.passed)
    handoffs = [
        (r.handoff_expected, r.handoff_actual)
        for r in rows
        if r.handoff_expected is not None and r.handoff_actual is not None
    ]
    recall = (
        metrics.handoff_counts(handoffs).recall
        if handoffs and any(e for e, _ in handoffs)
        else None
    )
    accuracy = [r.field_accuracy for r in rows if r.field_accuracy is not None]
    return {
        "id": run.id,
        "name": run.run_name,
        "created_at": iso(run.created_at),
        "prompt_version": run.prompt_version,
        "threshold": run.threshold,
        "tier": str(run.tier),
        "git_sha": run.git_sha,
        "suite": (run.snapshot or {}).get("suite", "unrecorded"),
        "results": len(rows),
        "scenarios": len(passes),
        "pass_rate": sum(r.passed for r in rows) / len(rows) if rows else None,
        "field_accuracy": metrics.spread(accuracy).mean if accuracy else None,
        "handoff_recall": recall,
        "flaky": metrics.flaky_scenarios(passes),
    }


@router.get("/evals")
def runs(
    session: Database, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
) -> dict[str, Any]:
    records = (
        session.execute(
            select(
                EvalRun.id,
                EvalRun.run_name.label("name"),
                EvalRun.created_at,
                EvalRun.prompt_version,
                EvalRun.threshold,
                EvalRun.tier,
                EvalRun.git_sha,
                EvalRun.snapshot["suite"].as_string().label("suite"),
            )
            .order_by(EvalRun.id.desc())
            .offset(offset)
            .limit(limit)
        )
        .mappings()
        .all()
    )
    run_ids = [row["id"] for row in records]
    groups = {}
    if run_ids:
        # Collapse repeated scenarios in SQL. Summary reads never fetch expected,
        # actual, transcript, notes or the full immutable persona snapshot.
        known_hot = and_(
            EvalResult.handoff_expected.is_(True), EvalResult.handoff_actual.is_not(None)
        )
        correct_hot = and_(
            EvalResult.handoff_expected.is_(True), EvalResult.handoff_actual.is_(True)
        )
        for row in session.execute(
            select(
                EvalResult.run_id,
                EvalResult.scenario_id,
                func.count().label("results"),
                func.sum(case((EvalResult.passed.is_(True), 1), else_=0)).label("passes"),
                func.sum(EvalResult.field_accuracy).label("accuracy_sum"),
                func.count(EvalResult.field_accuracy).label("accuracy_count"),
                func.sum(case((known_hot, 1), else_=0)).label("hot_count"),
                func.sum(case((correct_hot, 1), else_=0)).label("hot_correct"),
            )
            .where(EvalResult.run_id.in_(run_ids))
            .group_by(EvalResult.run_id, EvalResult.scenario_id)
        ):
            groups.setdefault(row.run_id, []).append(row)
    items = []
    for record in records:
        scenarios = groups.get(record["id"], [])
        count = sum(row.results for row in scenarios)
        accuracy_count = sum(row.accuracy_count for row in scenarios)
        hot_count = sum(row.hot_count for row in scenarios)
        items.append(
            {
                **record,
                "created_at": iso(record["created_at"]),
                "tier": str(record["tier"]),
                "suite": record["suite"] or "unrecorded",
                "results": count,
                "scenarios": len(scenarios),
                "pass_rate": sum(row.passes for row in scenarios) / count if count else None,
                "field_accuracy": sum(row.accuracy_sum or 0 for row in scenarios) / accuracy_count
                if accuracy_count
                else None,
                "handoff_recall": sum(row.hot_correct for row in scenarios) / hot_count
                if hot_count
                else None,
                "flaky": sorted(
                    row.scenario_id for row in scenarios if 0 < row.passes < row.results
                ),
            }
        )
    return {
        "items": items,
        "total": session.scalar(select(func.count(EvalRun.id))),
        "limit": limit,
        "offset": offset,
    }


@router.get("/evals/{run_id}")
def run_detail(
    run_id: Annotated[int, Path(gt=0, le=2_147_483_647)], session: Database
) -> dict[str, Any]:
    run = session.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(404, "Evaluation not found")
    groups = saved_groups(run.snapshot)
    return {
        **run_summary(run),
        "items": [
            {
                "id": row.id,
                "scenario_id": row.scenario_id,
                "group": groups.get(row.scenario_id, "unknown"),
                "repeat": row.repeat_index,
                "passed": row.passed,
                "field_accuracy": row.field_accuracy,
                "expected": row.expected,
                "actual": row.actual,
                "transcript": row.transcript,
                "notes": row.notes,
            }
            for row in sorted(run.results, key=lambda r: (r.scenario_id, r.repeat_index))
        ],
    }


@router.get("/compare")
def compare_runs(
    session: Database,
    before: Annotated[int, Query(gt=0, le=2_147_483_647)],
    after: Annotated[int, Query(gt=0, le=2_147_483_647)],
) -> dict[str, Any]:
    repo = EvalRepository(session)
    old, new = repo.get_run(before), repo.get_run(after)
    if old is None or new is None:
        raise HTTPException(404, "Evaluation not found")
    old_rows, new_rows = repo.results_for(before), repo.results_for(after)
    try:
        groups = comparison_groups(old, new, old_rows, new_rows)
    except InvalidComparison as exc:
        return {"status": "invalid", "reason": str(exc), "metrics": [], "regressions": []}
    deltas = []
    regressions = []
    for group in ["overall", *sorted(set(groups.values()))]:

        def subset(rows: list[EvalResult], group: str = group) -> list[EvalResult]:
            return (
                rows if group == "overall" else [r for r in rows if groups[r.scenario_id] == group]
            )

        a, b = _metrics_for(subset(old_rows)), _metrics_for(subset(new_rows))
        for name in a:
            delta = b[name] - a[name]
            guarded = group in REGRESSION_GUARDS.get(name, ())
            deltas.append(
                {
                    "group": group,
                    "name": name,
                    "before": a[name],
                    "after": b[name],
                    "delta": delta,
                    "guarded": guarded,
                }
            )
            if guarded and delta <= -NOISE_FLOOR:
                regressions.append({"group": group, "name": name, "delta": delta})
    return {
        "status": "regression" if regressions else "clear",
        "reason": None,
        "metrics": deltas,
        "regressions": regressions,
    }


@router.get("/operations")
def operations(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, Any]:
    """Configuration readiness and recent call health; no active vendor probes."""
    from arcagent.console.operations import operation_status

    return operation_status(settings)
