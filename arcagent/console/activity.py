"""Call-scoped staff activity with bounded cursor reads and minimized audit details."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from arcagent.console.api import Database, authenticate, iso
from arcagent.console.query_budget import limit_query_time
from arcagent.console.workflows import RecordId
from arcagent.persistence.models import Call
from arcagent.persistence.workflow_models import WorkflowAudit

router = APIRouter(prefix="/api/console", dependencies=[Depends(authenticate)], tags=["activity"])

# A timeline is an operational overview, not a copy of every historical audit payload.
# Private fields are named to explain that a change occurred; their values stay out.
_FIELDS = {
    "pipeline": frozenset(
        {
            "stage",
            "assignee",
            "location_id",
            "next_action_at",
            "notes",
            "contact_name",
            "callback_number",
        }
    ),
    "followup": frozenset({"status", "assignee", "notes"}),
    "feedback": frozenset(
        {"category", "synthetic_confirmed", "scenario", "expected_behavior", "review_note"}
    ),
    "integration": frozenset(
        {
            "destination",
            "location_id",
            "status",
            "attempt_count",
            "error_code",
            "review_id",
            "resolution",
            "provider_status",
            "review_revision",
            "evidence",
        }
    ),
}
_PRIVATE = frozenset(
    {
        "notes",
        "contact_name",
        "callback_number",
        "scenario",
        "expected_behavior",
        "review_note",
        "evidence",
    }
)
_ACTIONS = {
    "pipeline": frozenset({"updated"}),
    "followup": frozenset({"created", "updated"}),
    "feedback": frozenset({"created", "approved", "rejected"}),
    "integration": frozenset({"queued", "sending", "delivered", "failed", "uncertain", "reviewed"}),
}
_VALUES = {
    "stage": frozenset({"new", "contacted", "booked", "won", "lost"}),
    "destination": frozenset({"hubspot", "automation"}),
    "category": frozenset(
        {"missed_clarification", "incorrect_callback", "incorrect_routing", "other"}
    ),
    "resolution": frozenset({"verified_received", "verified_not_received", "needs_followup"}),
    "provider_status": frozenset({"queued", "sending", "delivered", "failed", "uncertain"}),
    "error_code": frozenset(
        {
            "location_changed",
            "configuration_changed",
            "destination_unavailable",
            "response_unknown",
            "rate_limited",
            "request_rejected",
            "worker_interrupted",
        }
    ),
}
_STATUSES = {
    "followup": frozenset({"open", "in_progress", "resolved"}),
    "integration": _VALUES["provider_status"],
}


def plain_string(value: Any, maximum: int) -> bool:
    return isinstance(value, str) and len(value) <= maximum and not any(ord(c) < 32 for c in value)


def safe_value(entity: str, key: str, value: Any) -> bool:
    if key in _PRIVATE:
        return False
    if value is None:
        return key in {"assignee", "location_id", "next_action_at", "error_code"}
    if key == "status":
        return isinstance(value, str) and value in _STATUSES.get(entity, ())
    if key in _VALUES:
        return isinstance(value, str) and value in _VALUES[key]
    if key == "assignee":
        return plain_string(value, 128)
    if key == "synthetic_confirmed":
        return type(value) is bool
    if key in {"location_id", "review_id", "review_revision"}:
        return type(value) is int and 1 <= value <= 2_147_483_647
    if key == "attempt_count":
        return type(value) is int and 0 <= value <= 3
    if key == "next_action_at" and plain_string(value, 40):
        try:
            return datetime.fromisoformat(value).tzinfo is not None
        except ValueError:
            return False
    return False


def activity_item(row: WorkflowAudit) -> dict[str, Any]:
    changes = row.changes if isinstance(row.changes, dict) else {}
    recognized = sorted(_FIELDS[row.entity].intersection(changes))
    return {
        "id": row.id,
        "entity": row.entity,
        "entity_id": row.entity_id,
        "revision": row.revision,
        "actor": row.actor if plain_string(row.actor, 128) else "unknown",
        "action": row.action if row.action in _ACTIONS[row.entity] else "recorded",
        "changes": {
            key: changes[key] for key in recognized if safe_value(row.entity, key, changes[key])
        },
        "fields_changed": recognized,
        "created_at": iso(row.created_at),
    }


@router.get("/calls/{call_id}/activity")
def activity(
    call_id: RecordId,
    session: Database,
    limit: int = Query(25, ge=1, le=100),
    before: int | None = Query(None, gt=0, le=2_147_483_647),
) -> dict[str, Any]:
    limit_query_time(session)
    if session.scalar(select(Call.id).where(Call.id == call_id)) is None:
        raise HTTPException(404, "Call not found")
    query = select(WorkflowAudit).where(
        WorkflowAudit.call_id == call_id, WorkflowAudit.entity.in_(_FIELDS)
    )
    if before is not None:
        query = query.where(WorkflowAudit.id < before)
    records = session.scalars(query.order_by(WorkflowAudit.id.desc()).limit(limit + 1)).all()
    selected = records[:limit]
    has_more = len(records) > limit
    return {
        "items": [activity_item(row) for row in selected],
        "limit": limit,
        "next_before": selected[-1].id if has_more else None,
        "has_more": has_more,
        "scope": "single_call_shared_workspace",
    }
