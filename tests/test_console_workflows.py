"""Durable coordinator edits and independently reviewed synthetic regression candidates."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from arcagent.config import Settings, get_settings
from arcagent.console.api import database
from arcagent.console.workflows import router
from arcagent.persistence.db import get_engine, session_scope
from arcagent.persistence.models import Base, Call
from arcagent.persistence.workflow_models import FollowupTask, WorkflowAudit


@pytest.fixture
def workspace(tmp_path):
    url = f"sqlite:///{tmp_path / 'workflow.db'}"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    with session_scope(url) as session:
        session.add(Call(twilio_call_sid="synthetic", from_number_hash="synthetic"))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, console_api_token="test-token"
    )

    def db():
        with session_scope(url) as session:
            yield session

    app.dependency_overrides[database] = db
    with TestClient(app) as client:
        client.headers.update({"Authorization": "Bearer test-token", "X-Arcagent-Actor": "author"})
        yield client, app, url
    engine.dispose()


def test_followup_dedup_revision_and_audit(workspace):
    client, _, url = workspace
    first = client.post("/api/console/followups", json={"call_id": 1})
    assert first.status_code == 201
    task = first.json()
    assert client.post("/api/console/followups", json={"call_id": 1}).json()["id"] == task["id"]
    result = client.patch(
        f"/api/console/followups/{task['id']}",
        json={
            "revision": 1,
            "status": "in_progress",
            "assignee": "coordinator",
            "notes": "Synthetic callback review",
        },
    )
    assert result.status_code == 200
    assert result.json()["revision"] == 2
    assert (
        client.patch(
            f"/api/console/followups/{task['id']}", json={"revision": 1, "status": "resolved"}
        ).status_code
        == 409
    )
    with session_scope(url) as session:
        assert session.get(FollowupTask, task["id"]).status == "in_progress"
        assert len(session.scalars(select(WorkflowAudit)).all()) == 2
    assert client.get("/api/console/followups?status=resolved").json()["total"] == 0
    assert len(client.get(f"/api/console/followups/{task['id']}/audit").json()["items"]) == 2


def test_feedback_requires_independent_review_and_exports_candidate_only(workspace):
    client, _, _ = workspace
    payload = {
        "call_id": 1,
        "category": "missed_clarification",
        "scenario": "A fictional caller gives an ambiguous answer.",
        "expected_behavior": "Ask a clarifying question.",
        "synthetic_confirmed": True,
        "client_request_id": "62e6a449-9b62-4191-8a30-8851f88cc927",
    }
    response = client.post("/api/console/feedback", json=payload)
    assert response.status_code == 201
    item = response.json()
    path = f"/api/console/feedback/{item['id']}"
    assert client.get(path + "/export").status_code == 409
    review = {
        "revision": 1,
        "decision": "approved",
        "review_note": "Checked synthetic wording and expected behavior.",
    }
    assert client.post(path + "/review", json=review).status_code == 403
    assert (
        client.post(
            path + "/review", json=review, headers={"X-Arcagent-Actor": "reviewer"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            path + "/review", json=review, headers={"X-Arcagent-Actor": "reviewer"}
        ).status_code
        == 409
    )
    exported = client.get(path + "/export").json()
    assert exported["kind"] == "regression_candidate"
    assert exported["automatically_executable"] is False
    assert "call_id" not in exported
    assert exported["scenario"] == payload["scenario"]


def test_auth_validation_missing_and_unavailable(workspace):
    client, app, _ = workspace
    assert client.post("/api/console/followups", json={"call_id": 99}).status_code == 404
    assert (
        client.post(
            "/api/console/followups", json={"call_id": 1}, headers={"X-Arcagent-Actor": ""}
        ).status_code
        == 401
    )
    assert client.get("/api/console/followups?limit=101").status_code == 422
    assert client.get("/api/console/followups?offset=999999999999999999999").status_code == 422
    assert client.get("/api/console/feedback/999999999999999999999/export").status_code == 422
    assert client.post("/api/console/followups", json={"call_id": 10**30}).status_code == 422
    assert (
        client.patch(
            "/api/console/followups/1", json={"revision": 1, "status": "dial_now"}
        ).status_code
        == 422
    )

    def forbidden():
        pytest.fail("Database opened without authentication")

    app.dependency_overrides[database] = forbidden
    assert client.get("/api/console/followups", headers={"Authorization": ""}).status_code == 401


def test_commit_failure_returns_503_and_rolls_back(workspace):
    client, app, url = workspace

    def failing_db():
        with session_scope(url) as session:

            def fail():
                raise OperationalError("secret connection", {}, Exception("secret"))

            session.commit = fail
            yield session

    app.dependency_overrides[database] = failing_db
    response = client.post("/api/console/followups", json={"call_id": 1})
    assert response.status_code == 503
    assert "secret" not in response.text
    with session_scope(url) as session:
        assert session.scalars(select(FollowupTask)).all() == []


def test_partial_update_preserves_notes_and_pagination_is_bounded(workspace):
    client, _, url = workspace
    with session_scope(url) as session:
        session.add(Call(twilio_call_sid="second", from_number_hash="synthetic"))
    first = client.post("/api/console/followups", json={"call_id": 1}).json()
    client.post("/api/console/followups", json={"call_id": 2})
    path = f"/api/console/followups/{first['id']}"
    client.patch(
        path,
        json={
            "revision": 1,
            "status": "in_progress",
            "notes": "Keep this note",
            "assignee": "team",
        },
    )
    response = client.patch(path, json={"revision": 2, "status": "resolved"})
    assert response.json()["notes"] == "Keep this note"
    assert response.json()["assignee"] == "team"
    page = client.get("/api/console/followups?limit=1&offset=1").json()
    assert page["total"] == 2
    assert [item["id"] for item in page["items"]] == [first["id"]]
    assert (
        client.patch(
            "/api/console/followups/999", json={"revision": 1, "status": "open"}
        ).status_code
        == 404
    )


def test_feedback_rejection_and_input_limits(workspace):
    client, _, _ = workspace
    payload = {
        "call_id": 1,
        "category": "other",
        "scenario": "Fictional caller asks an ambiguous question.",
        "expected_behavior": "Ask for clarification.",
        "synthetic_confirmed": True,
        "client_request_id": "62e6a449-9b62-4191-8a30-8851f88cc927",
    }
    assert (
        client.post(
            "/api/console/feedback", json={**payload, "synthetic_confirmed": False}
        ).status_code
        == 422
    )
    assert (
        client.post("/api/console/feedback", json={**payload, "scenario": "x" * 4001}).status_code
        == 422
    )
    assert (
        client.post("/api/console/feedback", json={**payload, "created_by": "spoofed"}).status_code
        == 422
    )
    item = client.post("/api/console/feedback", json=payload).json()
    response = client.post(
        f"/api/console/feedback/{item['id']}/review",
        json={
            "revision": 1,
            "decision": "rejected",
            "review_note": "Needs an explicit expected response.",
        },
        headers={"X-Arcagent-Actor": "reviewer"},
    )
    assert response.status_code == 200
    assert client.get(f"/api/console/feedback/{item['id']}/export").status_code == 409
    assert client.get("/api/console/feedback?status=rejected").json()["total"] == 1


def test_read_failure_is_sanitized_by_database_dependency(workspace, monkeypatch):
    from contextlib import contextmanager

    from arcagent.console import api

    client, app, _ = workspace
    app.dependency_overrides.pop(database)

    @contextmanager
    def unavailable():
        raise OperationalError("secret host", {}, Exception("credentials"))
        yield

    monkeypatch.setattr(api, "session_scope", unavailable)
    for path in ["/api/console/followups", "/api/console/feedback"]:
        response = client.get(path)
        assert response.status_code == 503
        assert "secret" not in response.text
        assert "credentials" not in response.text


def test_workflow_migration_preserves_calls_and_cascades_sensitive_work(tmp_path):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from alembic import command
    from arcagent.persistence.workflow_models import RegressionFeedback
    from tests.test_migrations import _alembic_config

    url = f"sqlite:///{tmp_path / 'migration-workflow.db'}"
    config = _alembic_config(url)
    command.upgrade(config, "b8e5f431a290")
    engine = create_engine(url)
    with Session(engine) as session:
        session.add(Call(twilio_call_sid="preserved", from_number_hash="synthetic"))
        session.commit()
    command.upgrade(config, "head")
    with Session(engine) as session:
        session.execute(text("PRAGMA foreign_keys=ON"))
        assert session.get(Call, 1).twilio_call_sid == "preserved"
        session.add(FollowupTask(call_id=1, created_by="author", updated_by="author"))
        session.add(
            RegressionFeedback(
                call_id=1,
                category="other",
                scenario="Synthetic scenario",
                expected_behavior="Clarify the question",
                created_by="author",
            )
        )
        session.add(
            WorkflowAudit(
                call_id=1,
                entity="followup",
                entity_id=1,
                revision=1,
                actor="author",
                action="created",
                changes={},
            )
        )
        session.commit()
        session.execute(text("DELETE FROM calls WHERE id=1"))
        session.commit()
        for model in [FollowupTask, RegressionFeedback, WorkflowAudit]:
            assert session.scalars(select(model)).all() == []
    command.downgrade(config, "b8e5f431a290")
    command.upgrade(config, "head")
    engine.dispose()


def test_feedback_create_is_idempotent_and_payload_bound(workspace):
    client, _, url = workspace
    payload = {
        "call_id": 1,
        "category": "other",
        "scenario": "A fictional caller is uncertain.",
        "expected_behavior": "Clarify the caller request.",
        "synthetic_confirmed": True,
        "client_request_id": "04029fc9-426d-4e3d-9618-870c31412d88",
    }
    first = client.post("/api/console/feedback", json=payload)
    assert first.status_code == 201
    retry = client.post("/api/console/feedback", json=payload)
    assert retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]
    assert (
        client.post(
            "/api/console/feedback", json={**payload, "scenario": "Different fictional scenario."}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/console/feedback", json=payload, headers={"X-Arcagent-Actor": "someone-else"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/console/feedback", json={**payload, "client_request_id": "not-a-uuid"}
        ).status_code
        == 422
    )
    assert client.get("/api/console/feedback").json()["total"] == 1
    with session_scope(url) as session:
        assert len(session.scalars(select(WorkflowAudit)).all()) == 1


def test_feedback_unique_race_recovers_without_second_audit(workspace, monkeypatch):
    from arcagent.console import workflows

    client, _, url = workspace
    payload = {
        "call_id": 1,
        "category": "other",
        "scenario": "A fictional caller is uncertain.",
        "expected_behavior": "Clarify the caller request.",
        "synthetic_confirmed": True,
        "client_request_id": "84029fc9-426d-4e3d-9618-870c31412d88",
    }
    first = client.post("/api/console/feedback", json=payload).json()
    original = workflows.feedback_retry
    seen = 0

    def miss_then_read(session, values, identity):
        nonlocal seen
        seen += 1
        # Simulate another request committing between the lookup and INSERT.
        return None if seen == 1 else original(session, values, identity)

    monkeypatch.setattr(workflows, "feedback_retry", miss_then_read)
    response = client.post("/api/console/feedback", json=payload)
    assert response.status_code == 200
    assert response.json()["id"] == first["id"]
    assert seen == 2
    with session_scope(url) as session:
        assert len(session.scalars(select(WorkflowAudit)).all()) == 1
