"""Reproducible synthetic SQLite query-shape evidence, never a latency benchmark.

Run: python -m scripts.profile_console_queries
Only creates a temporary local database. No production connection or vendor calls.
"""

import json
from datetime import UTC, datetime, timedelta
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine, event, func, insert, select
from sqlalchemy.orm import Session, selectinload

from arcagent.console.api import calls, runs
from arcagent.console.pipeline import pipeline
from arcagent.persistence.models import (
    Base,
    Call,
    Decision,
    EvalResult,
    EvalRun,
    Lead,
    LeadScore,
    Speaker,
    Turn,
)
from arcagent.persistence.pipeline_models import LeadPipeline
from arcagent.persistence.retention import candidates


def profile() -> dict:
    with TemporaryDirectory(prefix="arcagent-query-profile-") as directory:
        engine = create_engine(f"sqlite:///{directory}/synthetic.db")
        Base.metadata.create_all(engine)
        now = datetime.now(UTC)
        with engine.begin() as connection:
            connection.execute(
                insert(Call),
                [
                    {
                        "id": i,
                        "twilio_call_sid": f"synthetic-{i}",
                        "from_number_hash": "synthetic",
                        "started_at": now - timedelta(days=60, minutes=i),
                        "ended_at": now - timedelta(days=40 if i % 5 else 1),
                        "outcome": "HANDOFF",
                        "language": "en",
                    }
                    for i in range(1, 1001)
                ],
            )
            connection.execute(
                insert(Turn),
                [
                    {
                        "call_id": i,
                        "turn_index": 0,
                        "speaker": Speaker.CALLER,
                        "text": "synthetic transcript",
                    }
                    for i in range(1, 1001)
                ],
            )
            connection.execute(
                insert(Lead),
                [
                    {
                        "id": i,
                        "call_id": i,
                        "name": "Synthetic contact",
                        "objections": ["synthetic" * 100],
                    }
                    for i in range(1, 1001)
                ],
            )
            connection.execute(
                insert(LeadScore),
                [
                    {
                        "lead_id": i,
                        "score": n,
                        "threshold_used": 5,
                        "decision": Decision.HANDOFF,
                        "score_breakdown": {"synthetic": "x" * 1000},
                    }
                    for i in range(1, 1001)
                    for n in range(5)
                ],
            )
            connection.execute(
                insert(LeadPipeline),
                [
                    {
                        "call_id": i,
                        "stage": "contacted",
                        "next_action_at": now - timedelta(hours=i),
                        "updated_by": "synthetic",
                    }
                    for i in range(1, 1001)
                ],
            )
            connection.execute(
                insert(EvalRun),
                [
                    {
                        "id": 1,
                        "run_name": "synthetic",
                        "git_sha": "synthetic",
                        "prompt_version": "v1",
                        "threshold": 5,
                        "tier": "TEXT",
                        "snapshot": {"suite": "synthetic", "personas": "x" * 10000},
                    }
                ],
            )
            connection.execute(
                insert(EvalResult),
                [
                    {
                        "run_id": 1,
                        "scenario_id": f"synthetic-{i % 30}",
                        "passed": i % 2 == 0,
                        "transcript": [{"speaker": "agent", "text": "synthetic" * 1000}],
                        "field_accuracy": 1.0,
                    }
                    for i in range(300)
                ],
            )
        captured = []

        def capture(_connection, _cursor, statement, parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                captured.append((statement, parameters))

        def inspect_query(name, action):
            captured.clear()
            event.listen(engine, "before_cursor_execute", capture)
            try:
                with Session(engine) as session:
                    result = action(session)
            finally:
                event.remove(engine, "before_cursor_execute", capture)
            with engine.connect() as connection:
                plans = [
                    [
                        row[3]
                        for row in connection.exec_driver_sql(
                            "EXPLAIN QUERY PLAN " + statement, parameters
                        )
                    ]
                    for statement, parameters in captured
                ]
            return {
                "name": name,
                "select_count": len(captured),
                "items": len(result),
                "plans": plans,
            }

        def previous_call_load(session):
            # Exact previous list materialization shape, including its total.
            result = session.scalars(
                select(Call)
                .options(selectinload(Call.lead).selectinload(Lead.scores))
                .order_by(Call.started_at.desc(), Call.id.desc())
                .limit(50)
            ).all()
            session.scalar(select(func.count(Call.id)))
            return result

        evidence = [
            inspect_query("previous_call_page_with_count", previous_call_load),
            inspect_query(
                "call_page_with_count", lambda session: calls(session, 50, 0, None)["items"]
            ),
            inspect_query(
                "overdue_pipeline_with_summary",
                lambda session: pipeline(session, 50, 0, None, None, False, "overdue", None)[
                    "items"
                ],
            ),
            inspect_query("eval_page_with_count", lambda session: runs(session, 50, 0)["items"]),
        ]

        def retention_rows(session):
            return session.execute(candidates(now - timedelta(days=30)).limit(500)).all()

        evidence.append(inspect_query("retention_pending_index", retention_rows))
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP INDEX ix_turns_pending_transcript_id")
        evidence.append(inspect_query("retention_without_pending_index", retention_rows))
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE INDEX experiment_calls_ended_id ON calls (ended_at, id)"
            )
        evidence.append(inspect_query("retention_experimental_ended_index", retention_rows))
        engine.dispose()
        return {
            "database": "temporary synthetic SQLite",
            "calls": 1000,
            "scores_per_call": 5,
            "eval_results": 300,
            "evidence": evidence,
            "limitation": (
                "Query shape and planner evidence only; "
                "not a PostgreSQL or production latency measurement."
            ),
        }


if __name__ == "__main__":
    print(json.dumps(profile(), indent=2))
