"""Read-only retention visibility, with bounded counts and no sensitive payloads."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import SQLAlchemyError

from arcagent.config import Settings, get_settings
from arcagent.console.api import authenticate
from arcagent.persistence.db import session_scope
from arcagent.persistence.retention import retention_preview

router = APIRouter(prefix="/api/console", dependencies=[Depends(authenticate)], tags=["console"])


@router.get("/storage")
def storage(
    settings: Annotated[Settings, Depends(get_settings)],
    limit: int = Query(1000, ge=1, le=1000),
) -> dict[str, Any]:
    try:
        with session_scope(settings.database_url) as session:
            preview = retention_preview(
                session, days=settings.transcript_retention_days, limit=limit
            )
    except SQLAlchemyError:
        preview = None
    return {
        "database": {"available": preview is not None},
        "retention": preview,
        "automation": "manual_only",
        "physical_storage_bytes": None,
        "preserved": [
            "turn_rows_and_latency",
            "calls_and_leads",
            "workflow_audits",
            "delivery_and_idempotency_records",
            "evaluation_results",
        ],
    }
