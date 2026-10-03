"""Pilot prerequisites do not imply live acceptance or fabricate an empty backlog."""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from arcagent.config import Settings, get_settings
from arcagent.console.pilot import router
from arcagent.persistence.db import get_engine, session_scope
from arcagent.persistence.integration_models import IntegrationDelivery
from arcagent.persistence.models import Base, Call, Lead
from arcagent.persistence.pipeline_models import LeadPipeline, Location


@pytest.fixture
def pilot_client(tmp_path):
    url = f"sqlite:///{tmp_path / 'pilot.db'}"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    settings = Settings(_env_file=None, database_url=url, console_api_token="fixture")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client, settings
    engine.dispose()


def read(client):
    return client.get("/api/console/pilot", headers={"Authorization": "Bearer fixture"})


def test_pilot_authentication_precedes_all_readiness_work(pilot_client, monkeypatch):
    client, settings = pilot_client

    def forbidden(*args, **kwargs):
        raise AssertionError("Unauthenticated request reached readiness")

    monkeypatch.setattr("arcagent.console.pilot.operation_status", forbidden)
    for authorization in ["", "Bearer wrong", "Basic fixture"]:
        assert (
            client.get("/api/console/pilot", headers={"Authorization": authorization}).status_code
            == 401
        )
    settings.console_api_token = ""
    assert client.get("/api/console/pilot").status_code == 503


def test_empty_database_is_real_zero_but_not_a_ready_pilot(pilot_client):
    client, _ = pilot_client
    response = read(client)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["summary"] == {
        "active_locations": 0,
        "unassigned_leads": 0,
        "crm_deliveries_pending": 0,
        "crm_deliveries_uncertain": 0,
    }
    assert data["database"]["available"]
    assert data["configuration_ready"] is False
    assert data["live_validation"] == "not_verified"
    assert data["scope"] == {
        "workspace": "single_group",
        "authorization": "shared_workspace_members",
        "location_isolation": False,
        "records": "all_stored_leads",
    }


def test_backlog_uses_unique_enquiries_and_does_not_expose_payloads(pilot_client):
    client, settings = pilot_client
    with session_scope(settings.database_url) as db:
        active = Location(name="private-active", timezone="UTC", updated_by="private-actor")
        inactive = Location(
            name="private-inactive", timezone="UTC", active=False, updated_by="private-actor"
        )
        db.add_all([active, inactive])
        db.flush()
        for index, status in enumerate(["queued", "sending", "uncertain", "delivered", "failed"]):
            call = Call(twilio_call_sid=f"private-{index}", from_number_hash="private-hash")
            db.add(call)
            db.flush()
            db.add(Lead(call_id=call.id, name="private-name", callback_number="private-phone"))
            if index == 0:
                db.add(Lead(call_id=call.id, name="private-duplicate"))
            if index > 0:
                db.add(
                    LeadPipeline(
                        call_id=call.id,
                        location_id=active.id if index > 1 else None,
                        updated_by="private-actor",
                    )
                )
            db.add(
                IntegrationDelivery(
                    call_id=call.id,
                    location_id=active.id,
                    location_name=active.name,
                    destination="automation",
                    client_request_id=str(uuid4()),
                    status=status,
                    payload={"private-contact": "private-value"},
                    config_fingerprint="private-secret",
                    created_by="private-actor",
                    updated_by="private-actor",
                )
            )
    response = read(client)
    assert response.json()["summary"] == {
        "active_locations": 1,
        "unassigned_leads": 2,
        "crm_deliveries_pending": 2,
        "crm_deliveries_uncertain": 1,
    }
    assert "private" not in response.text
    assert any(
        item["id"] == "delivery_reconciliation" and item["status"] == "blocked"
        for item in response.json()["checks"]
    )


@pytest.mark.parametrize("failing_module", ["pilot", "operations"])
def test_database_outage_is_unavailable_not_zero(pilot_client, monkeypatch, failing_module):
    client, _ = pilot_client

    def unavailable(*args, **kwargs):
        raise OperationalError("private-query", {}, Exception("private-secret"))

    monkeypatch.setattr(f"arcagent.console.{failing_module}.session_scope", unavailable)
    response = read(client)
    assert response.status_code == 200
    assert response.json()["summary"] is None
    assert response.json()["database"] == {"available": False}
    assert response.json()["configuration_ready"] is False
    assert "private" not in response.text


def test_configuration_success_never_claims_live_acceptance(
    pilot_client, monkeypatch, ready_prompts
):
    client, settings = pilot_client
    for field in [
        "twilio_account_sid",
        "twilio_auth_token",
        "twilio_number",
        "coordinator_number",
        "deepgram_api_key",
        "cartesia_api_key",
        "cartesia_voice_id",
        "llm_api_key",
    ]:
        setattr(settings, field, "private-secret")
    settings.public_url = "https://private.example"
    monkeypatch.setattr(
        "arcagent.console.pilot.integration_readiness",
        lambda _: [
            {"destination": "automation", "configured": True, "detail": "private-detail"},
        ],
    )
    with session_scope(settings.database_url) as db:
        db.add(Location(name="private-location", timezone="UTC", updated_by="private-actor"))
    response = read(client)
    data = response.json()
    assert data["configuration_ready"] is True
    assert data["live_validation"] == "not_verified"
    assert {check["id"] for check in data["checks"] if check["status"] == "unknown"} == {
        "vendor_connectivity",
        "workspace_identity",
        "pilot_acceptance",
    }
    assert "private" not in response.text
