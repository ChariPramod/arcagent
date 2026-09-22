"""Run explicitly in isolated staging with runtime credentials, never on real caller data."""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select, text

from arcagent.persistence.db import session_scope
from arcagent.persistence.models import Call, Outcome
from arcagent.persistence.repo import CallRepository


def main() -> None:
    with session_scope() as session:
        version = session.scalar(text("SELECT version_num FROM alembic_version"))
        assert version == "d72fc801ab34", "schema revision mismatch"
        role = session.execute(
            text(
                "SELECT rolcreatedb, rolcreaterole, rolsuper FROM pg_roles "
                "WHERE rolname=current_user"
            )
        ).one()
        assert not any(role), "runtime role has elevated flags"
        elevated = session.scalar(
            text("SELECT pg_has_role(current_user, 'cloudsqlsuperuser', 'member')")
        )
        assert not elevated, "runtime role inherits Cloud SQL administration"
        owned_schemas = session.scalar(
            text(
                "SELECT count(*) FROM pg_namespace "
                "WHERE nspowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)"
            )
        )
        assert owned_schemas == 0, "runtime owns a schema"
        call = session.scalar(
            select(Call).where(Call.twilio_call_sid == "synthetic-staging-smoke-20260922")
        )
        if call is None:
            call = Call(
                twilio_call_sid="synthetic-staging-smoke-20260922",
                from_number_hash=hashlib.sha256(b"synthetic-staging-smoke").hexdigest(),
                ended_at=datetime.now(UTC),
                outcome=Outcome.ABANDONED,
                final_node="synthetic_staging_smoke",
            )
            session.add(call)
            session.flush()
        CallRepository(session).save_lead(
            call.id, {"name": "Synthetic staging smoke (not a real call)"}
        )
        result = {"schema": version, "runtime_elevated": False, "synthetic_call_id": call.id}
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
