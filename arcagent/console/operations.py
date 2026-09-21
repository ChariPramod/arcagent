"""Read-only configuration readiness and recent persisted call health.

Ready means required configuration is present and the database query succeeded. This
endpoint does not verify vendor credentials or make speech, model, or telephone calls.
"""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from arcagent.agent.readiness import inspect_prompts
from arcagent.config import Settings
from arcagent.persistence.db import session_scope
from arcagent.persistence.models import Call, Outcome


def operation_status(settings: Settings) -> dict:
    now = datetime.now(UTC)
    issues = inspect_prompts(settings.prompt_version)
    checks = []

    def check(identifier: str, label: str, configured: bool, detail: str) -> None:
        checks.append(
            {
                "id": identifier,
                "label": label,
                "status": "ready" if configured else "blocked",
                "detail": detail,
            }
        )

    check(
        "prompts",
        "Agent prompts",
        not issues,
        "Checks the effective cached prompt bundle for missing, empty, or unfinished prompts.",
    )
    for identifier, label, fields in (
        (
            "telephony",
            "Telephony configuration",
            ("twilio_account_sid", "twilio_auth_token", "twilio_number", "coordinator_number"),
        ),
        ("speech_recognition", "Speech recognition configuration", ("deepgram_api_key",)),
        (
            "speech_generation",
            "Speech generation configuration",
            ("cartesia_api_key", "cartesia_voice_id", "cartesia_model_id"),
        ),
        ("language_model", "Language model configuration", ("llm_api_key", "llm_model")),
    ):
        check(
            identifier,
            label,
            all(bool(getattr(settings, field).strip()) for field in fields),
            "Checks required configuration only. Credentials and connectivity are not verified.",
        )
    try:
        public = urlsplit(settings.public_url)
        valid_url = bool(
            public.scheme == "https"
            and public.hostname
            and not public.username
            and not public.password
            and not public.query
            and not public.fragment
        )
    except ValueError:
        valid_url = False
    check(
        "public_endpoint",
        "Public voice endpoint",
        valid_url,
        "Requires an HTTPS public URL; reachability has not been verified.",
    )
    check(
        "signature_validation",
        "Twilio signature validation",
        settings.env == "prod" or settings.validate_twilio_signature,
        "Incoming voice requests must verify Twilio signatures.",
    )
    checks.append(
        {
            "id": "vendor_connectivity",
            "label": "Live vendor validation",
            "status": "unknown",
            "detail": (
                "No active vendor probes are performed. Ready indicates configuration only, "
                "not validated live operation."
            ),
        }
    )

    summary = None
    failures = []
    available = False
    cutoff = now - timedelta(hours=24)
    incomplete = or_(Call.ended_at.is_(None), Call.outcome.is_(None))
    try:
        with session_scope(settings.database_url) as session:
            totals = session.execute(
                select(
                    func.count(Call.id),
                    func.sum(case((Call.outcome == Outcome.ABANDONED, 1), else_=0)),
                    func.sum(case((incomplete, 1), else_=0)),
                ).where(Call.started_at >= cutoff, Call.started_at <= now)
            ).one()
            rows = session.execute(
                select(Call.id, Call.started_at, Call.outcome)
                .where(
                    Call.started_at >= cutoff,
                    Call.started_at <= now,
                    or_(Call.outcome == Outcome.ABANDONED, incomplete),
                )
                .order_by(Call.started_at.desc(), Call.id.desc())
                .limit(10)
            ).all()
            summary = {
                "recent_calls": int(totals[0]),
                "abandoned_calls": int(totals[1] or 0),
                "incomplete_calls": int(totals[2] or 0),
            }
            failures = [
                {
                    "id": row.id,
                    "started_at": (
                        row.started_at.replace(tzinfo=UTC)
                        if row.started_at.tzinfo is None
                        else row.started_at
                    ).isoformat(),
                    "outcome": row.outcome,
                }
                for row in rows
            ]
        available = True
    except SQLAlchemyError:
        summary = None
        failures = []
    check(
        "database",
        "Call database",
        available,
        "Recent call records were read successfully."
        if available
        else "Call records could not be read. No recent counts are available.",
    )
    return {
        "checked_at": now.isoformat(),
        "readiness": {
            "ready": all(item["status"] != "blocked" for item in checks),
            "prompt_version": settings.prompt_version
            if not any(issue.reason == "invalid_version" for issue in issues)
            else "invalid",
            "issues": [asdict(issue) for issue in issues],
            "checks": checks,
        },
        "recent_failures": failures,
        "summary": summary,
        "database": {"available": available},
    }
