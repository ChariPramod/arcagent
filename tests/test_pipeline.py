"""Operator conversion is independent, revision protected and location scoped."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from arcagent.config import Settings, get_settings
from arcagent.console.api import database
from arcagent.console.pipeline import router
from arcagent.persistence.db import get_engine, session_scope
from arcagent.persistence.models import Base, Call, Lead, Outcome
from arcagent.persistence.pipeline_models import LeadPipeline, LocationAudit
from arcagent.persistence.workflow_models import WorkflowAudit


@pytest.fixture
def console(tmp_path):
    url = f"sqlite:///{tmp_path / 'pipeline.db'}"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, console_api_token="fixture-token"
    )

    def db():
        with session_scope(url) as session:
            yield session

    app.dependency_overrides[database] = db
    with session_scope(url) as session:
        for index in range(3):
            call = Call(
                twilio_call_sid=f"pipeline-{index}",
                from_number_hash="hash",
                outcome=Outcome.CALLBACK_BOOKED,
            )
            session.add(call)
            session.flush()
            session.add(Lead(call_id=call.id, name=f"Synthetic lead {index}"))
    with TestClient(app) as client:
        client.headers.update(
            {"Authorization": "Bearer fixture-token", "X-Arcagent-Actor": "operator"}
        )
        yield client, url, app
    engine.dispose()


def test_new_leads_lazy_state_and_stage_is_independent(console):
    client, url, _ = console
    response = client.get("/api/console/pipeline")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["summary"] == {
        "new": 3,
        "contacted": 0,
        "booked": 0,
        "won": 0,
        "lost": 0,
        "total": 3,
    }
    assert data["scope"] == "all_stored_leads_single_group"
    row = data["items"][0]
    assert row["revision"] == 0 and row["location_id"] is None
    with session_scope(url) as session:
        assert session.scalars(select(LeadPipeline)).all() == []
    changed = client.patch(
        f"/api/console/pipeline/{row['call_id']}",
        json={
            "revision": 0,
            "stage": "booked",
            "assignee": "Alex",
            "notes": "Requested follow-up",
            "next_action_at": "2026-10-03T10:00:00-07:00",
        },
    )
    assert changed.status_code == 200
    assert changed.json()["revision"] == 1
    assert changed.json()["next_action_at"] == "2026-10-03T17:00:00+00:00"
    assert changed.json()["call_outcome"] == "callback_booked"
    partial = client.patch(
        f"/api/console/pipeline/{row['call_id']}", json={"revision": 1, "stage": "won"}
    )
    assert partial.json()["notes"] == "Requested follow-up"
    assert partial.json()["assignee"] == "Alex"
    assert client.get("/api/console/pipeline?stage=won").json()["total"] == 1
    audits = client.get(f"/api/console/pipeline/{row['call_id']}/audit").json()
    assert audits["total"] == 2 and audits["items"][0]["actor"] == "operator"


def test_stale_revision_rejects_without_extra_audit(console):
    client, url, _ = console
    assert (
        client.patch("/api/console/pipeline/1", json={"revision": 0, "notes": "first"}).status_code
        == 200
    )
    assert (
        client.patch("/api/console/pipeline/1", json={"revision": 0, "notes": "lost"}).status_code
        == 409
    )
    with session_scope(url) as session:
        assert session.scalar(select(LeadPipeline)).notes == "first"
        assert len(session.scalars(select(WorkflowAudit)).all()) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"revision": 0},
        {"revision": 0, "stage": None},
        {"revision": 0, "notes": None},
        {"revision": 0, "next_action_at": "2026-10-03T10:00:00"},
        {"revision": 0, "stage": "imaginary"},
        {"revision": 0, "extra": "rejected"},
    ],
)
def test_invalid_edits_rejected(console, payload):
    client, _, _ = console
    assert client.patch("/api/console/pipeline/1", json=payload).status_code == 422


def test_locations_scope_counts_and_reject_inactive_assignment(console):
    client, url, _ = console
    created = client.post(
        "/api/console/locations", json={"name": "North", "timezone": "America/Los_Angeles"}
    )
    assert created.status_code == 201
    location = created.json()
    location_id = location["id"]
    assert (
        client.patch(
            "/api/console/pipeline/1",
            json={"revision": 0, "location_id": location_id, "stage": "contacted"},
        ).status_code
        == 200
    )
    scoped = client.get(f"/api/console/pipeline?location_id={location_id}").json()
    assert scoped["summary"]["total"] == 1 and scoped["summary"]["contacted"] == 1
    assert scoped["items"][0]["location_name"] == "North"
    assert client.get("/api/console/pipeline?unassigned=true").json()["summary"]["total"] == 2
    assert (
        client.get(f"/api/console/pipeline?unassigned=true&location_id={location_id}").status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/console/locations/{location_id}", json={"revision": 1, "active": False}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/console/locations/{location_id}", json={"revision": 1, "name": "Overwrite"}
        ).status_code
        == 409
    )
    assert (
        client.patch(
            "/api/console/pipeline/2", json={"revision": 0, "location_id": location_id}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/console/pipeline/1", json={"revision": 1, "notes": "Preserved inactive location"}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            "/api/console/pipeline/1", json={"revision": 2, "location_id": None}
        ).status_code
        == 200
    )
    assert client.get("/api/console/pipeline?unassigned=true").json()["total"] == 3
    assert client.get(f"/api/console/locations/{location_id}/audit").json()["total"] == 2
    with session_scope(url) as session:
        assert len(session.scalars(select(LocationAudit)).all()) == 2


def test_auth_precedes_database_and_writes_require_actor(console):
    client, _, app = console
    client.headers.pop("X-Arcagent-Actor")
    assert (
        client.patch("/api/console/pipeline/1", json={"revision": 0, "stage": "won"}).status_code
        == 401
    )

    def forbidden():
        pytest.fail("unauthenticated database access")

    app.dependency_overrides[database] = forbidden
    assert (
        client.get("/api/console/pipeline", headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )
    assert (
        client.get("/api/console/locations", headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )


def test_location_timezone_validation_and_missing_enquiry(console):
    client, _, _ = console
    assert (
        client.post(
            "/api/console/locations", json={"name": "North", "timezone": "Imaginary/Zone"}
        ).status_code
        == 422
    )
    assert (
        client.post("/api/console/locations", json={"name": " ", "timezone": "UTC"}).status_code
        == 422
    )
    assert (
        client.patch("/api/console/pipeline/999", json={"revision": 0, "stage": "won"}).status_code
        == 404
    )
    assert client.get("/api/console/pipeline?limit=101").status_code == 422


def test_duplicate_historic_leads_do_not_double_count(console):
    client, url, _ = console
    with session_scope(url) as session:
        session.add(Lead(call_id=1, name="Most recent"))
    data = client.get("/api/console/pipeline").json()
    assert data["total"] == 3
    assert next(row for row in data["items"] if row["call_id"] == 1)["name"] == "Most recent"


def test_database_commit_failure_rolls_back_state_and_audit(console, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    client, url, _ = console
    original = Session.commit

    def unavailable(self):
        raise OperationalError("private-db-details", {}, Exception("failure"))

    monkeypatch.setattr(Session, "commit", unavailable)
    response = client.patch("/api/console/pipeline/1", json={"revision": 0, "stage": "won"})
    assert response.status_code == 503
    assert "private-db-details" not in response.text
    monkeypatch.setattr(Session, "commit", original)
    with session_scope(url) as session:
        assert session.scalars(select(LeadPipeline)).all() == []
        assert session.scalars(select(WorkflowAudit)).all() == []


def test_pipeline_migration_upgrade_downgrade(tmp_path):
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    from alembic import command

    url = f"sqlite:///{tmp_path / 'migrations.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "e83ad902bc45")
    engine = create_engine(url)
    assert {"locations", "lead_pipeline", "location_audit"} <= set(
        inspect(engine).get_table_names()
    )
    command.downgrade(config, "d72fc801ab34")
    assert "lead_pipeline" not in inspect(engine).get_table_names()
    command.upgrade(config, "e83ad902bc45")
    assert "location_id" in {c["name"] for c in inspect(engine).get_columns("lead_pipeline")}
    engine.dispose()


def test_contact_correction_updates_latest_lead_with_revision_and_audit(console):
    client, url, _ = console
    with session_scope(url) as session:
        session.add(Lead(call_id=1, name="Latest captured", callback_number="invalid"))
    result = client.patch(
        "/api/console/pipeline/1",
        json={
            "revision": 0,
            "contact_name": "  Synthetic corrected  ",
            "callback_number": "+12025550123",
        },
    )
    assert result.status_code == 200
    assert result.json()["name"] == "Synthetic corrected"
    assert result.json()["callback_number"] == "+12025550123"
    assert result.json()["revision"] == 1
    audit = client.get("/api/console/pipeline/1/audit").json()["items"][0]
    assert audit["changes"]["contact_name"] == "Synthetic corrected"
    assert audit["changes"]["callback_number"] == "+12025550123"
    with session_scope(url) as session:
        leads = session.scalars(select(Lead).where(Lead.call_id == 1).order_by(Lead.id)).all()
        assert leads[0].name == "Synthetic lead 0"
        assert leads[1].name == "Synthetic corrected"
    stale = client.patch(
        "/api/console/pipeline/1", json={"revision": 0, "contact_name": "Lost edit"}
    )
    assert stale.status_code == 409
    changed = client.patch("/api/console/pipeline/1", json={"revision": 1, "stage": "contacted"})
    assert changed.json()["name"] == "Synthetic corrected"
    assert changed.json()["callback_number"] == "+12025550123"


@pytest.mark.parametrize(
    "fields",
    [
        {"contact_name": " "},
        {"contact_name": None},
        {"callback_number": None},
        {"callback_number": "2025550123"},
        {"callback_number": "+02025550123"},
        {"callback_number": "+1202555012345678"},
        {"callback_number": "+123"},
    ],
)
def test_invalid_contact_corrections_rejected(console, fields):
    client, _, _ = console
    assert (
        client.patch("/api/console/pipeline/1", json={"revision": 0, **fields}).status_code == 422
    )


def test_contact_edits_rollback_when_audit_commit_fails(console, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    client, url, _ = console
    original = Session.commit

    def fail(self):
        raise OperationalError("hidden", {}, Exception())

    monkeypatch.setattr(Session, "commit", fail)
    assert (
        client.patch(
            "/api/console/pipeline/1", json={"revision": 0, "contact_name": "Unsaved"}
        ).status_code
        == 503
    )
    monkeypatch.setattr(Session, "commit", original)
    with session_scope(url) as session:
        assert session.scalar(select(Lead).where(Lead.call_id == 1)).name == "Synthetic lead 0"
        assert session.scalars(select(LeadPipeline)).all() == []


def test_due_and_owner_filters_scope_summary_before_stage_and_pagination(console):
    client, _, _ = console
    for call_id, changes in [
        (1, {"stage": "contacted", "next_action_at": "2000-01-01T00:00:00Z"}),
        (2, {"stage": "booked", "next_action_at": "2099-01-01T00:00:00Z", "assignee": "Alex"}),
    ]:
        assert (
            client.patch(
                f"/api/console/pipeline/{call_id}", json={"revision": 0, **changes}
            ).status_code
            == 200
        )
    overdue = client.get("/api/console/pipeline?due=overdue&owner=unassigned").json()
    assert [row["call_id"] for row in overdue["items"]] == [1]
    assert overdue["summary"] == {
        "new": 0,
        "contacted": 1,
        "booked": 0,
        "won": 0,
        "lost": 0,
        "total": 1,
    }
    filtered = client.get("/api/console/pipeline?due=overdue&stage=new&offset=1").json()
    assert filtered["items"] == [] and filtered["total"] == 0
    assert filtered["summary"]["contacted"] == 1
    assert [
        row["call_id"] for row in client.get("/api/console/pipeline?due=scheduled").json()["items"]
    ] == [2]
    assert [
        row["call_id"]
        for row in client.get("/api/console/pipeline?due=unscheduled").json()["items"]
    ] == [3]
    assert client.get("/api/console/pipeline?due=scheduled&owner=unassigned").json()["total"] == 0
    assert (
        client.patch("/api/console/pipeline/1", json={"revision": 1, "stage": "won"}).status_code
        == 200
    )
    assert client.get("/api/console/pipeline?due=overdue").json()["total"] == 0
    for query in ("due=today", "owner=someone", "due="):
        assert client.get(f"/api/console/pipeline?{query}").status_code == 422


def test_unassigned_owner_includes_legacy_blank_values_and_no_workflow(console):
    client, url, _ = console
    with session_scope(url) as session:
        session.add(LeadPipeline(call_id=1, assignee="  ", updated_by="legacy"))
        session.add(LeadPipeline(call_id=2, assignee="Staff", updated_by="legacy"))
    data = client.get("/api/console/pipeline?owner=unassigned&limit=1").json()
    assert data["total"] == 2 and data["summary"]["total"] == 2
    assert len(data["items"]) == 1
