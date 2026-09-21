"""Operations reports configuration and persisted recent call health without caller data."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arcagent.config import Settings, get_settings
from arcagent.console.api import router
from arcagent.persistence.db import get_engine, session_scope
from arcagent.persistence.models import Base, Call, Outcome


@pytest.fixture
def operations(tmp_path):
    url = f"sqlite:///{tmp_path / 'operations.db'}"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    settings = Settings(_env_file=None, database_url=url, console_api_token="fixture")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client, settings
    engine.dispose()


def test_operations_requires_authentication_before_database_work(operations, monkeypatch):
    client, settings = operations

    def forbidden(*args, **kwargs):
        raise AssertionError("unauthenticated request reached database")

    monkeypatch.setattr("arcagent.persistence.db.get_engine", forbidden)
    for header in ["", "Bearer wrong", "Basic fixture"]:
        assert (
            client.get("/api/console/operations", headers={"Authorization": header}).status_code
            == 401
        )
    settings.console_api_token = ""
    assert client.get("/api/console/operations").status_code == 503


def test_operations_counts_recent_calls_without_returning_caller_data(operations, ready_prompts):
    client, settings = operations
    for field in (
        "twilio_account_sid",
        "twilio_auth_token",
        "twilio_number",
        "coordinator_number",
        "deepgram_api_key",
        "cartesia_api_key",
        "cartesia_voice_id",
        "llm_api_key",
    ):
        setattr(settings, field, "private-secret")
    settings.public_url = "https://private.example"
    now = datetime.now(UTC)
    with session_scope(settings.database_url) as db:
        db.add_all(
            [
                Call(
                    twilio_call_sid="private-one",
                    from_number_hash="private-hash",
                    started_at=now - timedelta(hours=1),
                    ended_at=now,
                    outcome=Outcome.HANDOFF,
                ),
                Call(
                    twilio_call_sid="private-two",
                    from_number_hash="private-hash",
                    started_at=now - timedelta(hours=2),
                    ended_at=now,
                    outcome=Outcome.ABANDONED,
                ),
                Call(
                    twilio_call_sid="private-three",
                    from_number_hash="private-hash",
                    started_at=now - timedelta(hours=3),
                ),
                Call(
                    twilio_call_sid="private-old",
                    from_number_hash="private-hash",
                    started_at=now - timedelta(days=2),
                    outcome=Outcome.ABANDONED,
                ),
            ]
        )
    response = client.get("/api/console/operations", headers={"Authorization": "Bearer fixture"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["summary"] == {"recent_calls": 3, "abandoned_calls": 1, "incomplete_calls": 1}
    assert data["database"] == {"available": True}
    assert data["readiness"]["ready"] is True
    assert data["readiness"]["issues"] == []
    assert len(data["recent_failures"]) == 2
    assert all(set(row) == {"id", "started_at", "outcome"} for row in data["recent_failures"])
    assert "private" not in response.text
    assert any(
        check["id"] == "vendor_connectivity" and check["status"] == "unknown"
        for check in data["readiness"]["checks"]
    )


def test_database_outage_returns_partial_status_without_error_details(operations, monkeypatch):
    from sqlalchemy.exc import OperationalError

    client, _ = operations

    def unavailable(*args, **kwargs):
        raise OperationalError("private-query", {}, Exception("private-password"))

    monkeypatch.setattr("arcagent.console.operations.session_scope", unavailable)
    response = client.get("/api/console/operations", headers={"Authorization": "Bearer fixture"})
    assert response.status_code == 200
    data = response.json()
    assert data["database"] == {"available": False}
    assert data["summary"] is None
    assert data["recent_failures"] == []
    assert data["readiness"]["ready"] is False
    assert any(
        check["id"] == "database" and check["status"] == "blocked"
        for check in data["readiness"]["checks"]
    )
    assert "private" not in response.text


def test_missing_configuration_and_placeholders_are_reported_safely(operations):
    client, settings = operations
    response = client.get("/api/console/operations", headers={"Authorization": "Bearer fixture"})
    data = response.json()
    assert not data["readiness"]["ready"]
    assert {issue["reason"] for issue in data["readiness"]["issues"]} == {"placeholder"}
    assert data["summary"] == {"recent_calls": 0, "abandoned_calls": 0, "incomplete_calls": 0}
    settings.prompt_version = "../private-secret"
    response = client.get("/api/console/operations", headers={"Authorization": "Bearer fixture"})
    assert response.json()["readiness"]["prompt_version"] == "invalid"
    assert "private-secret" not in response.text


def test_recent_failures_are_bounded_and_ordered_newest_first(operations):
    client, settings = operations
    now = datetime.now(UTC)
    with session_scope(settings.database_url) as db:
        for index in range(13):
            db.add(
                Call(
                    twilio_call_sid=f"fixture-{index}",
                    from_number_hash="fixture",
                    started_at=now - timedelta(minutes=index + 1),
                    outcome=Outcome.ABANDONED,
                    ended_at=now,
                )
            )
    response = client.get("/api/console/operations", headers={"Authorization": "Bearer fixture"})
    data = response.json()
    assert data["summary"]["abandoned_calls"] == 13
    assert len(data["recent_failures"]) == 10
    timestamps = [row["started_at"] for row in data["recent_failures"]]
    assert timestamps == sorted(timestamps, reverse=True)
