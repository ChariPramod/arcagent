"""Read-only group pilot prerequisites and persisted backlog, without vendor probes."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from arcagent.config import Settings, get_settings
from arcagent.console.api import authenticate
from arcagent.console.operations import operation_status
from arcagent.integrations.service import integration_readiness
from arcagent.persistence.db import session_scope
from arcagent.persistence.integration_models import IntegrationDelivery
from arcagent.persistence.models import Lead
from arcagent.persistence.pipeline_models import LeadPipeline, Location

router = APIRouter(prefix="/api/console", dependencies=[Depends(authenticate)], tags=["pilot"])


def pilot_status(settings: Settings) -> dict:
    operations = operation_status(settings)
    checks = list(operations["readiness"]["checks"])
    integrations = integration_readiness(settings)
    checks.append(
        {
            "id": "crm_configuration",
            "label": "CRM delivery configuration",
            "status": "ready" if any(item["configured"] for item in integrations) else "blocked",
            "detail": "A supported destination must be configured. Delivery is not verified.",
        }
    )
    summary = None
    available = operations["database"]["available"]
    try:
        with session_scope(settings.database_url) as session:
            # Historical imports may contain more than one lead per call. Count
            # the same unique enquiry set as the pipeline, including test records.
            unassigned = session.scalar(
                select(func.count(func.distinct(Lead.call_id)))
                .outerjoin(LeadPipeline, LeadPipeline.call_id == Lead.call_id)
                .where(LeadPipeline.location_id.is_(None))
            )
            locations = session.scalar(
                select(func.count(Location.id)).where(Location.active.is_(True))
            )
            statuses = dict(
                session.execute(
                    select(IntegrationDelivery.status, func.count()).group_by(
                        IntegrationDelivery.status
                    )
                ).all()
            )
            if available:
                summary = {
                    "active_locations": locations,
                    "unassigned_leads": unassigned,
                    "crm_deliveries_pending": statuses.get("queued", 0)
                    + statuses.get("sending", 0),
                    "crm_deliveries_uncertain": statuses.get("uncertain", 0),
                }
    except SQLAlchemyError:
        available = False
    if not available:
        # A successful call query cannot hide missing migrations or an outage in
        # the pipeline/integration tables. Null does not mean an empty backlog.
        summary = None
        checks = [item for item in checks if item["id"] != "database"]
        checks.append(
            {
                "id": "database",
                "label": "Pilot database",
                "status": "blocked",
                "detail": "Pilot records could not be read. Backlog counts are unavailable.",
            }
        )
    checks.extend(
        [
            {
                "id": "locations",
                "label": "Active group locations",
                "status": "ready" if summary and summary["active_locations"] > 0 else "blocked",
                "detail": (
                    "An active location is required. Location labels do not restrict member access."
                ),
            },
            {
                "id": "delivery_reconciliation",
                "label": "Uncertain CRM deliveries",
                "status": (
                    "unknown"
                    if summary is None
                    else "blocked"
                    if summary["crm_deliveries_uncertain"]
                    else "ready"
                ),
                "detail": "Reconcile uncertain delivery at the destination before another send.",
            },
            {
                "id": "workspace_identity",
                "label": "Website access validation",
                "status": "unknown",
                "detail": "Website identity and member access are not verified here.",
            },
            {
                "id": "pilot_acceptance",
                "label": "Controlled pilot acceptance",
                "status": "unknown",
                "detail": "Review call, transfer, CRM and recovery evidence before live use.",
            },
        ]
    )
    return {
        "checked_at": operations["checked_at"],
        "configuration_ready": all(item["status"] != "blocked" for item in checks),
        "live_validation": "not_verified",
        "scope": {
            "workspace": "single_group",
            "authorization": "shared_workspace_members",
            "location_isolation": False,
            "records": "all_stored_leads",
        },
        "checks": checks,
        "summary": summary,
        "database": {"available": available},
    }


@router.get("/pilot")
def pilot(settings: Settings = Depends(get_settings)) -> dict:
    return pilot_status(settings)
