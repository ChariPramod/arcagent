"""Authenticated human work; never dials, sends SMS, or modifies production evals."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from arcagent.console.api import Database, authenticate, iso
from arcagent.persistence.models import Call
from arcagent.persistence.workflow_models import FollowupTask, RegressionFeedback, WorkflowAudit

router = APIRouter(prefix="/api/console", dependencies=[Depends(authenticate)], tags=["workflows"])
Status = Literal["open", "in_progress", "resolved"]
FeedbackStatus = Literal["pending", "approved", "rejected"]


def actor(x_arcagent_actor: Annotated[str | None, Header()] = None) -> str:
    # Only the authenticated server proxy may supply this identity. Do not expose the bearer.
    if not x_arcagent_actor or not x_arcagent_actor.strip() or len(x_arcagent_actor) > 128:
        raise HTTPException(401, "Verified workspace identity required")
    if any(ord(c) < 32 for c in x_arcagent_actor):
        raise HTTPException(401, "Verified workspace identity required")
    return x_arcagent_actor.strip()


Actor = Annotated[str, Depends(actor)]
RecordId = Annotated[int, Path(gt=0, le=2_147_483_647)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateFollowup(Input):
    call_id: int = Field(gt=0, le=2_147_483_646)


class EditFollowup(Input):
    revision: int = Field(gt=0, le=2_147_483_646)
    status: Status
    assignee: str | None = Field(default=None, max_length=128)
    notes: str = Field(default="", max_length=4000)


class CreateFeedback(Input):
    client_request_id: UUID
    call_id: int = Field(gt=0, le=2_147_483_646)
    category: Literal["missed_clarification", "incorrect_callback", "incorrect_routing", "other"]
    scenario: str = Field(min_length=10, max_length=4000)
    expected_behavior: str = Field(min_length=10, max_length=4000)
    synthetic_confirmed: Literal[True]


class ReviewFeedback(Input):
    revision: int = Field(gt=0, le=2_147_483_646)
    decision: Literal["approved", "rejected"]
    review_note: str = Field(min_length=10, max_length=2000)


def commit(session: Session) -> None:
    try:
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(503, "The workspace database is unavailable") from exc


def required(session: Session, model, item_id: int):
    record = session.get(model, item_id)
    if record is None:
        raise HTTPException(404, "Record not found")
    return record


def serialize(record) -> dict:
    return {
        column.name: iso(value)
        if isinstance(value := getattr(record, column.name), datetime)
        else value
        for column in record.__table__.columns
    }


def audit(session: Session, record, entity: str, identity: str, action: str, changes: dict):
    session.add(
        WorkflowAudit(
            call_id=record.call_id,
            entity=entity,
            entity_id=record.id,
            revision=record.revision,
            actor=identity,
            action=action,
            changes=changes,
        )
    )


def page(session: Session, model, limit: int, offset: int, status: str | None) -> dict:
    query = select(model)
    count = select(func.count(model.id))
    if status:
        query, count = query.where(model.status == status), count.where(model.status == status)
    return {
        "items": [
            serialize(row)
            for row in session.scalars(query.order_by(model.id.desc()).limit(limit).offset(offset))
        ],
        "total": session.scalar(count),
        "limit": limit,
        "offset": offset,
    }


@router.get("/followups")
def followups(
    session: Database,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
    status: Status | None = None,
):
    return page(session, FollowupTask, limit, offset, status)


@router.post("/followups", status_code=201)
def create_followup(body: CreateFollowup, session: Database, identity: Actor, response: Response):
    required(session, Call, body.call_id)
    existing = session.scalar(select(FollowupTask).where(FollowupTask.call_id == body.call_id))
    if existing:
        response.status_code = 200
        return serialize(existing)
    record = FollowupTask(call_id=body.call_id, created_by=identity, updated_by=identity)
    try:
        session.add(record)
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(FollowupTask).where(FollowupTask.call_id == body.call_id))
        if existing is None:
            raise HTTPException(409, "Call changed; refresh before retrying") from None
        response.status_code = 200
        return serialize(existing)
    audit(session, record, "followup", identity, "created", {"status": "open"})
    result = serialize(record)
    commit(session)
    return result


@router.patch("/followups/{item_id}")
def edit_followup(item_id: RecordId, body: EditFollowup, session: Database, identity: Actor):
    record = required(session, FollowupTask, item_id)
    # Only fields explicitly supplied are changed; an omitted note is never silently erased.
    changes = body.model_dump(exclude={"revision"}, exclude_unset=True)
    values = {
        **changes,
        "revision": body.revision + 1,
        "updated_by": identity,
        "updated_at": datetime.now(UTC),
    }
    result = session.execute(
        update(FollowupTask)
        .where(FollowupTask.id == item_id, FollowupTask.revision == body.revision)
        .values(**values)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "This task changed; refresh before retrying")
    session.refresh(record)
    audit(session, record, "followup", identity, "updated", changes)
    payload = serialize(record)
    commit(session)
    return payload


@router.get("/followups/{item_id}/audit")
def followup_audit(
    item_id: RecordId,
    session: Database,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
):
    required(session, FollowupTask, item_id)
    predicate = (WorkflowAudit.entity == "followup", WorkflowAudit.entity_id == item_id)
    return {
        "items": [
            serialize(row)
            for row in session.scalars(
                select(WorkflowAudit)
                .where(*predicate)
                .order_by(WorkflowAudit.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ],
        "total": session.scalar(select(func.count(WorkflowAudit.id)).where(*predicate)),
        "limit": limit,
        "offset": offset,
    }


@router.get("/feedback")
def feedback(
    session: Database,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
    status: FeedbackStatus | None = None,
):
    return page(session, RegressionFeedback, limit, offset, status)


def feedback_retry(session: Session, values: dict, identity: str):
    existing = session.scalar(
        select(RegressionFeedback).where(
            RegressionFeedback.client_request_id == values["client_request_id"]
        )
    )
    if existing is not None and (
        existing.created_by != identity
        or any(getattr(existing, key) != value for key, value in values.items())
    ):
        raise HTTPException(409, "This submission key was already used; refresh before retrying")
    return existing


@router.post("/feedback", status_code=201)
def create_feedback(body: CreateFeedback, session: Database, identity: Actor, response: Response):
    values = body.model_dump(mode="json", exclude={"synthetic_confirmed"})
    existing = feedback_retry(session, values, identity)
    if existing is not None:
        response.status_code = 200
        return serialize(existing)
    required(session, Call, body.call_id)
    record = RegressionFeedback(**values, created_by=identity)
    try:
        session.add(record)
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = feedback_retry(session, values, identity)
        if existing is None:
            raise HTTPException(409, "Call changed; refresh before retrying") from None
        response.status_code = 200
        return serialize(existing)
    audit(
        session,
        record,
        "feedback",
        identity,
        "created",
        {"category": body.category, "synthetic_confirmed": True},
    )
    payload = serialize(record)
    commit(session)
    return payload


@router.post("/feedback/{item_id}/review")
def review_feedback(item_id: RecordId, body: ReviewFeedback, session: Database, identity: Actor):
    record = required(session, RegressionFeedback, item_id)
    if record.created_by == identity:
        raise HTTPException(403, "An independent reviewer must review this candidate")
    result = session.execute(
        update(RegressionFeedback)
        .where(
            RegressionFeedback.id == item_id,
            RegressionFeedback.revision == body.revision,
            RegressionFeedback.status == "pending",
        )
        .values(
            status=body.decision,
            reviewed_by=identity,
            reviewed_at=datetime.now(UTC),
            review_note=body.review_note,
            revision=body.revision + 1,
        )
    )
    if result.rowcount != 1:
        raise HTTPException(409, "This feedback changed; refresh before retrying")
    session.refresh(record)
    audit(session, record, "feedback", identity, body.decision, {"review_note": body.review_note})
    payload = serialize(record)
    commit(session)
    return payload


@router.get("/feedback/{item_id}/export")
def export_feedback(item_id: RecordId, session: Database):
    record = required(session, RegressionFeedback, item_id)
    if record.status != "approved":
        raise HTTPException(409, "Independent approval is required before export")
    return {
        "schema_version": 1,
        "kind": "regression_candidate",
        "automatically_executable": False,
        "scenario_id": f"feedback-{record.id}-r{record.revision}",
        "category": record.category,
        "scenario": record.scenario,
        "expected_behavior": record.expected_behavior,
        "data_classification": "reviewed_synthetic",
        "next_step": (
            "Implement explicit assertions and review the fixture "
            "before adding it to an evaluation suite."
        ),
    }
