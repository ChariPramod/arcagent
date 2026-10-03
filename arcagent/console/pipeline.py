"""Single-group conversion tracking. Includes all stored leads, including test records."""

from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, Field, field_validator, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from arcagent.console.api import Database, authenticate, iso
from arcagent.console.workflows import Actor, Input, RecordId, audit, commit, serialize
from arcagent.persistence.models import Call, Lead
from arcagent.persistence.pipeline_models import LeadPipeline, Location, LocationAudit
from arcagent.persistence.workflow_models import WorkflowAudit

router = APIRouter(prefix="/api/console", dependencies=[Depends(authenticate)], tags=["pipeline"])
Stage = Literal["new", "contacted", "booked", "won", "lost"]
STAGES = ("new", "contacted", "booked", "won", "lost")


class EditPipeline(Input):
    contact_name: str | None = Field(default=None, min_length=1, max_length=128)
    callback_number: str | None = Field(default=None, pattern=r"^\+[1-9]\d{7,14}$")
    revision: int = Field(ge=0, le=2_147_483_646)
    location_id: int | None = Field(default=None, gt=0, le=2_147_483_647)
    stage: Stage | None = None
    assignee: str | None = Field(default=None, max_length=128)
    next_action_at: AwareDatetime | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_changes(self):
        if not self.model_fields_set - {"revision"}:
            raise ValueError("At least one change is required")
        for name in ("stage", "notes", "contact_name", "callback_number"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} must not be null")
        return self


def item(call, lead, state, location_name):
    return {
        "call_id": call.id,
        "lead_id": lead.id,
        "name": lead.name,
        "callback_number": lead.callback_number,
        "started_at": iso(call.started_at),
        "call_outcome": str(call.outcome) if call.outcome else None,
        "location_id": state.location_id if state else None,
        "location_name": location_name,
        "stage": state.stage if state else "new",
        "assignee": state.assignee if state else None,
        "next_action_at": iso(state.next_action_at) if state else None,
        "notes": state.notes if state else "",
        "revision": state.revision if state else 0,
        "updated_at": iso(state.updated_at) if state else None,
    }


def rows():
    # Historical schemas do not constrain lead.call_id uniquely. Treat one call
    # as one enquiry and deterministically use its latest saved lead record.
    latest = select(func.max(Lead.id).label("lead_id")).group_by(Lead.call_id).subquery()
    return (
        select(Call, Lead, LeadPipeline, Location.name)
        .join(Lead, Lead.call_id == Call.id)
        .join(latest, latest.c.lead_id == Lead.id)
        .outerjoin(LeadPipeline, LeadPipeline.call_id == Call.id)
        .outerjoin(Location, Location.id == LeadPipeline.location_id)
    )


@router.get("/pipeline")
def pipeline(
    session: Database,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
    stage: Stage | None = None,
    location_id: int | None = Query(None, gt=0, le=2_147_483_647),
    unassigned: bool = False,
):
    base = rows()
    if location_id is not None and unassigned:
        raise HTTPException(422, "Choose a location or unassigned, not both")
    if location_id is not None:
        base = base.where(LeadPipeline.location_id == location_id)
    elif unassigned:
        base = base.where(LeadPipeline.location_id.is_(None))
    # Aggregate the same enquiry set used for pagination, never infer revenue.
    grouped = base.with_only_columns(
        func.coalesce(LeadPipeline.stage, "new").label("stage")
    ).subquery()
    counts = dict(
        session.execute(select(grouped.c.stage, func.count()).group_by(grouped.c.stage)).all()
    )
    summary = {name: counts.get(name, 0) for name in STAGES}
    summary["total"] = sum(summary.values())
    filtered = base.where(func.coalesce(LeadPipeline.stage, "new") == stage) if stage else base
    return {
        "items": [
            item(*row)
            for row in session.execute(
                filtered.order_by(Call.started_at.desc(), Call.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ],
        "total": counts.get(stage, 0) if stage else summary["total"],
        "limit": limit,
        "offset": offset,
        "summary": summary,
        "scope": "all_stored_leads_single_group",
    }


@router.patch("/pipeline/{call_id}")
def edit_pipeline(call_id: RecordId, body: EditPipeline, session: Database, identity: Actor):
    found = session.execute(rows().where(Call.id == call_id)).first()
    if found is None:
        raise HTTPException(404, "Lead enquiry not found")
    call, lead, state, _location_name = found
    changes = body.model_dump(exclude={"revision"}, exclude_unset=True)
    if changes.get("next_action_at") is not None:
        changes["next_action_at"] = changes["next_action_at"].astimezone(UTC)
    if changes.get("location_id") is not None:
        location = session.scalar(
            select(Location).where(Location.id == changes["location_id"]).with_for_update()
        )
        if location is None or not location.active:
            raise HTTPException(422, "Assign an active location")
    contacts = {
        key: changes.pop(key) for key in ("contact_name", "callback_number") if key in changes
    }
    now = datetime.now(UTC)
    if state is None:
        if body.revision != 0:
            raise HTTPException(409, "Enquiry changed; refresh before saving")
        state = LeadPipeline(
            call_id=call_id, **changes, revision=1, updated_by=identity, updated_at=now
        )
        session.add(state)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "Enquiry changed; refresh before saving") from None
    else:
        result = session.execute(
            update(LeadPipeline)
            .where(LeadPipeline.id == state.id, LeadPipeline.revision == body.revision)
            .values(**changes, revision=body.revision + 1, updated_at=now, updated_by=identity)
        )
        if result.rowcount != 1:
            session.rollback()
            raise HTTPException(409, "Enquiry changed; refresh before saving")
        session.refresh(state)
    # Apply contact edits only after acquiring the workflow revision. Both writes
    # and their audit commit together; omitted captured details are untouched.
    if "contact_name" in contacts:
        lead.name = contacts["contact_name"]
    if "callback_number" in contacts:
        lead.callback_number = contacts["callback_number"]
    audit_changes = {
        key: iso(value) if isinstance(value, datetime) else value
        for key, value in {**changes, **contacts}.items()
    }
    audit(session, state, "pipeline", identity, "updated", audit_changes)
    location = session.get(Location, state.location_id) if state.location_id else None
    result = item(call, lead, state, location.name if location else None)
    commit(session)
    return result


@router.get("/pipeline/{call_id}/audit")
def pipeline_audit(
    call_id: RecordId,
    session: Database,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
):
    if session.execute(rows().where(Call.id == call_id)).first() is None:
        raise HTTPException(404, "Lead enquiry not found")
    query = select(WorkflowAudit).where(
        WorkflowAudit.call_id == call_id, WorkflowAudit.entity == "pipeline"
    )
    return {
        "items": [
            serialize(row)
            for row in session.scalars(
                query.order_by(WorkflowAudit.id.desc()).limit(limit).offset(offset)
            )
        ],
        "total": session.scalar(select(func.count()).select_from(query.subquery())),
        "limit": limit,
        "offset": offset,
    }


class LocationFields(Input):
    name: str = Field(min_length=1, max_length=128)
    timezone: str = Field(min_length=1, max_length=64)
    active: bool = True

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Use a valid IANA timezone") from None
        return value


class EditLocation(Input):
    revision: int = Field(gt=0, le=2_147_483_646)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    active: bool | None = None

    @model_validator(mode="after")
    def validate_changes(self):
        fields = self.model_fields_set - {"revision"}
        if not fields or any(getattr(self, key) is None for key in fields):
            raise ValueError("Supply at least one non-null change")
        if self.timezone is not None:
            LocationFields.timezone_exists(self.timezone)
        return self


def location_item(record):
    return {key: value for key, value in serialize(record).items() if key != "updated_by"}


@router.get("/locations")
def locations(
    session: Database,
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
):
    return {
        "items": [
            location_item(row)
            for row in session.scalars(
                select(Location).order_by(Location.name, Location.id).limit(limit).offset(offset)
            )
        ],
        "total": session.scalar(select(func.count(Location.id))),
        "limit": limit,
        "offset": offset,
    }


@router.post("/locations", status_code=201)
def create_location(body: LocationFields, session: Database, identity: Actor):
    record = Location(
        **body.model_dump(), updated_by=identity, revision=1, updated_at=datetime.now(UTC)
    )
    session.add(record)
    session.flush()
    session.add(
        LocationAudit(location_id=record.id, revision=1, actor=identity, changes=body.model_dump())
    )
    result = location_item(record)
    commit(session)
    return result


@router.patch("/locations/{location_id}")
def edit_location(location_id: RecordId, body: EditLocation, session: Database, identity: Actor):
    record = session.get(Location, location_id)
    if record is None:
        raise HTTPException(404, "Location not found")
    changes = body.model_dump(exclude={"revision"}, exclude_unset=True)
    result = session.execute(
        update(Location)
        .where(Location.id == location_id, Location.revision == body.revision)
        .values(
            **changes, revision=body.revision + 1, updated_by=identity, updated_at=datetime.now(UTC)
        )
    )
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "Location changed; refresh before saving")
    session.refresh(record)
    session.add(
        LocationAudit(
            location_id=record.id, revision=record.revision, actor=identity, changes=changes
        )
    )
    result = location_item(record)
    commit(session)
    return result


@router.get("/locations/{location_id}/audit")
def location_audit(
    location_id: RecordId,
    session: Database,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
):
    if session.get(Location, location_id) is None:
        raise HTTPException(404, "Location not found")
    query = select(LocationAudit).where(LocationAudit.location_id == location_id)
    return {
        "items": [
            serialize(row)
            for row in session.scalars(
                query.order_by(LocationAudit.id.desc()).limit(limit).offset(offset)
            )
        ],
        "total": session.scalar(select(func.count()).select_from(query.subquery())),
        "limit": limit,
        "offset": offset,
    }
