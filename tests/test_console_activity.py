"""A bounded staff timeline reveals workflow evidence without copying private notes."""

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from arcagent.config import Settings, get_settings
from arcagent.console.activity import router
from arcagent.console.api import database
from arcagent.persistence.db import get_engine, session_scope
from arcagent.persistence.models import Base, Call
from arcagent.persistence.workflow_models import WorkflowAudit


@pytest.fixture
def workspace(tmp_path):
    url = f"sqlite:///{tmp_path / 'activity.db'}"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    with session_scope(url) as session:
        session.add_all(
            [
                Call(twilio_call_sid="fixture-one", from_number_hash="fixture"),
                Call(twilio_call_sid="fixture-two", from_number_hash="fixture"),
            ]
        )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, console_api_token="fixture"
    )

    def db():
        with session_scope(url) as session:
            yield session

    app.dependency_overrides[database] = db
    with TestClient(app) as client:
        client.headers.update({"Authorization": "Bearer fixture"})
        yield client, app, url
    engine.dispose()


def add_event(url, *, call_id=1, entity="pipeline", action="updated", changes=None):
    with session_scope(url) as session:
        row = WorkflowAudit(
            call_id=call_id,
            entity=entity,
            entity_id=1,
            revision=1,
            actor="coordinator",
            action=action,
            changes=changes or {},
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        session.add(row)
        session.flush()
        return row.id


def test_authentication_precedes_call_or_audit_queries(workspace):
    client, app, _ = workspace

    def forbidden():
        pytest.fail("Database opened before authentication")

    app.dependency_overrides[database] = forbidden
    assert (
        client.get("/api/console/calls/1/activity", headers={"Authorization": ""}).status_code
        == 401
    )
    assert (
        client.get(
            "/api/console/calls/1/activity", headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )


def test_call_scoped_timeline_uses_stable_cursor_despite_new_inserts(workspace):
    client, _, url = workspace
    ids = [add_event(url) for _ in range(5)]
    add_event(url, call_id=2)
    first = client.get("/api/console/calls/1/activity?limit=2")
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    page = first.json()
    assert [row["id"] for row in page["items"]] == ids[-1:-3:-1]
    assert page["next_before"] == ids[-2]
    assert page["has_more"] is True
    add_event(url)
    second = client.get(
        f"/api/console/calls/1/activity?limit=2&before={page['next_before']}"
    ).json()
    assert [row["id"] for row in second["items"]] == ids[-3:-5:-1]
    third = client.get(
        f"/api/console/calls/1/activity?limit=2&before={second['next_before']}"
    ).json()
    assert [row["id"] for row in third["items"]] == ids[:1]
    assert third["next_before"] is None and third["has_more"] is False
    assert page["scope"] == "single_call_shared_workspace"


def test_safe_changes_and_private_field_names_are_explicitly_allowlisted(workspace):
    client, _, url = workspace
    add_event(
        url,
        changes={
            "stage": "contacted",
            "assignee": "coordinator",
            "location_id": 7,
            "next_action_at": "2026-10-03T13:00:00+00:00",
            "notes": "private-note",
            "contact_name": "private-contact",
            "callback_number": "+12025550123",
            "unknown-private-key": "private-payload",
            "status": "not-a-pipeline-field",
        },
    )
    response = client.get("/api/console/calls/1/activity")
    item = response.json()["items"][0]
    assert item["changes"] == {
        "stage": "contacted",
        "assignee": "coordinator",
        "location_id": 7,
        "next_action_at": "2026-10-03T13:00:00+00:00",
    }
    assert item["fields_changed"] == [
        "assignee",
        "callback_number",
        "contact_name",
        "location_id",
        "next_action_at",
        "notes",
        "stage",
    ]
    assert "private" not in response.text
    assert "+12025550123" not in response.text


def test_feedback_and_crm_review_entries_exclude_evidence_text(workspace):
    client, _, url = workspace
    add_event(url, entity="feedback", action="approved", changes={"review_note": "private-review"})
    add_event(
        url,
        entity="integration",
        action="reviewed",
        changes={
            "review_id": 12,
            "resolution": "verified_received",
            "provider_status": "uncertain",
            "attempt_count": 1,
            "review_revision": 2,
            "evidence": "private-receipt",
        },
    )
    response = client.get("/api/console/calls/1/activity")
    review, feedback = response.json()["items"]
    assert review["action"] == "reviewed"
    assert review["changes"]["provider_status"] == "uncertain"
    assert review["changes"]["resolution"] == "verified_received"
    assert "evidence" in review["fields_changed"]
    assert feedback["changes"] == {} and feedback["fields_changed"] == ["review_note"]
    assert "private" not in response.text


def test_unknown_entities_invalid_values_and_arbitrary_metadata_are_not_exposed(workspace):
    client, _, url = workspace
    add_event(url, entity="private-entity", action="private-action", changes={"private": "value"})
    add_event(
        url,
        entity="integration",
        action="private-action",
        changes={
            "status": "private-status",
            "destination": {"private": "payload"},
            "error_code": "private-secret",
            "location_id": True,
            "attempt_count": 100,
            "resolution": "private-resolution",
        },
    )
    response = client.get("/api/console/calls/1/activity")
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["action"] == "recorded"
    assert items[0]["changes"] == {}
    assert "private" not in response.text


def test_missing_call_and_empty_timeline_are_distinct(workspace):
    client, _, _ = workspace
    assert client.get("/api/console/calls/999/activity").status_code == 404
    empty = client.get("/api/console/calls/1/activity").json()
    assert empty["items"] == [] and empty["has_more"] is False
    assert empty["next_before"] is None


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=101", "before=0", "before=-1", "before=2147483648"]
)
def test_page_bounds(workspace, query):
    client, _, _ = workspace
    assert client.get(f"/api/console/calls/1/activity?{query}").status_code == 422


def test_page_fetch_is_bounded_without_total_count_or_private_table_reads(workspace):
    client, _, url = workspace
    for _ in range(20):
        add_event(url)
    queries = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append((statement, parameters))

    engine = get_engine(url)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        data = client.get("/api/console/calls/1/activity?limit=3").json()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(data["items"]) == 3 and data["has_more"] is True
    assert len(queries) == 2
    audit_query = next(row for row in queries if "workflow_audit" in row[0])
    assert "LIMIT" in audit_query[0] and 4 in audit_query[1]
    assert not any(
        "count(" in row[0].lower() or "leads" in row[0] or "turns" in row[0] for row in queries
    )


def test_database_failure_uses_existing_sanitized_dependency(workspace, monkeypatch):
    from contextlib import contextmanager

    from arcagent.console import api

    client, app, _ = workspace
    app.dependency_overrides.pop(database)

    @contextmanager
    def unavailable():
        raise OperationalError("private-host", {}, Exception("private-secret"))
        yield

    monkeypatch.setattr(api, "session_scope", unavailable)
    response = client.get("/api/console/calls/1/activity")
    assert response.status_code == 503
    assert "private" not in response.text
