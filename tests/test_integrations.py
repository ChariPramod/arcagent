"""Contact-only delivery, endpoint access, duplicate prevention and uncertain outcomes."""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from arcagent.config import get_settings
from arcagent.console.api import database
from arcagent.integrations import api, service, worker
from arcagent.integrations.service import configured_destination, resolve_public_address
from arcagent.persistence.db import get_engine, get_session_factory, session_scope
from arcagent.persistence.integration_models import IntegrationDelivery
from arcagent.persistence.models import Base, Call, Lead
from arcagent.persistence.pipeline_models import LeadPipeline, Location
from arcagent.persistence.workflow_models import WorkflowAudit


@pytest.fixture
def integration(tmp_path):
    url = f"sqlite:///{tmp_path / 'integrations.db'}"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    with session_scope(url) as session:
        session.add(
            Call(id=1, twilio_call_sid="synthetic-integration", from_number_hash="fictional")
        )
        session.add(
            Location(
                id=1, name="Fictional clinic", timezone="America/Los_Angeles", updated_by="owner"
            )
        )
        session.flush()
        session.add(
            Lead(
                call_id=1,
                name="Fictional Person",
                callback_number="+12025550123",
                treatment_interest="never-export-medical",
                employer_name="never-export",
            )
        )
        session.add(LeadPipeline(call_id=1, location_id=1, updated_by="owner"))
    settings = SimpleNamespace(
        console_api_token="test-console",
        hubspot_access_token="secret-crm",
        automation_webhook_url="https://hooks.zapier.com/hooks/catch/12/secret",
        integration_delivery_timeout_s=3,
        database_url=url,
    )
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_settings] = lambda: settings

    def db():
        with session_scope(url) as session:
            yield session

    app.dependency_overrides[database] = db
    with TestClient(app) as client:
        client.headers.update({"Authorization": "Bearer test-console", "X-Arcagent-Actor": "owner"})
        yield client, settings, get_session_factory(url)
    engine.dispose()


def queue(integration, destination="hubspot"):
    client, _, _ = integration
    result = client.post(
        "/api/console/integrations/deliveries",
        json={"call_id": 1, "destination": destination, "client_request_id": str(uuid4())},
    )
    assert result.status_code == 201, result.text
    return result.json()


def test_queue_is_contact_only_snapshotted_audited_and_idempotent(integration):
    client, _, factory = integration
    request = {"call_id": 1, "destination": "hubspot", "client_request_id": str(uuid4())}
    first = client.post("/api/console/integrations/deliveries", json=request)
    assert first.status_code == 201
    assert client.post("/api/console/integrations/deliveries", json=request).status_code == 200
    request["client_request_id"] = str(uuid4())
    assert (
        client.post("/api/console/integrations/deliveries", json=request).json()["id"]
        == first.json()["id"]
    )
    with factory() as session:
        row = session.get(IntegrationDelivery, first.json()["id"])
        assert row.payload == {
            "contact": {"name": "Fictional Person", "phone": "+12025550123"},
            "location": {"id": 1, "name": "Fictional clinic"},
        }
        session.get(Location, 1).name = "Changed after queue"
        session.commit()
        assert row.location_name == "Fictional clinic"
        audit = session.scalar(select(WorkflowAudit))
        assert audit.actor == "owner" and audit.action == "queued"
        assert "phone" not in str(audit.changes)
    for response in [
        first,
        client.get("/api/console/integrations/deliveries"),
        client.get("/api/console/integrations"),
    ]:
        for private in [
            "secret-crm",
            "hooks.zapier.com",
            "never-export",
        ]:
            assert private not in response.text
    assert client.get("/api/console/integrations/deliveries?location_id=2").json()["total"] == 0


def test_uuid_cannot_be_rebound_to_another_intent(integration):
    client, _, _ = integration
    body = {"call_id": 1, "destination": "hubspot", "client_request_id": str(uuid4())}
    assert client.post("/api/console/integrations/deliveries", json=body).status_code == 201
    body["destination"] = "automation"
    assert client.post("/api/console/integrations/deliveries", json=body).status_code == 409


def test_auth_config_location_and_contact_gates(integration):
    client, settings, factory = integration
    path = "/api/console/integrations/deliveries"
    body = {"call_id": 1, "destination": "hubspot", "client_request_id": str(uuid4())}
    assert client.get("/api/console/integrations", headers={"Authorization": ""}).status_code == 401
    assert client.post(path, json=body, headers={"X-Arcagent-Actor": ""}).status_code == 401
    settings.hubspot_access_token = ""
    assert client.post(path, json=body).status_code == 503
    settings.hubspot_access_token = "secret-crm"
    with factory() as session:
        session.get(Location, 1).active = False
        session.commit()
    assert client.post(path, json=body).status_code == 409
    with factory() as session:
        session.get(Location, 1).active = True
        session.scalar(select(Lead)).callback_number = "not a phone"
        session.commit()
    assert client.post(path, json=body).status_code == 409
    body["url"] = "https://attacker.example"
    assert client.post(path, json=body).status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.zapier.com/hooks/catch/x",
        "https://127.0.0.1/webhook/x",
        "https://hooks.zapier.com.evil.example/hooks/catch/x",
        "https://user:password@hooks.zapier.com/hooks/catch/x",
        "https://hook.eu1.make.com:444/secret",
        "https://hooks.zapier.com/hooks/catch/x?redirect=bad",
        "https://custom.example/webhook/x",
        "https://hooks.zapier.com\\@localhost/hooks/catch/x",
    ],
)
def test_destination_urls_fail_closed(url):
    assert configured_destination(SimpleNamespace(automation_webhook_url=url), "automation") is None


@pytest.mark.parametrize(
    "url",
    [
        "https://hooks.zapier.com/hooks/catch/1/key",
        "https://hook.eu1.make.com/key",
        "https://clinic.app.n8n.cloud/webhook/key",
    ],
)
def test_supported_cloud_webhooks_and_public_dns(url):
    destination = configured_destination(SimpleNamespace(automation_webhook_url=url), "automation")
    assert destination

    def answer(ip):
        return [(2, 1, 6, "", (ip, 443))]

    assert resolve_public_address(destination, lambda *a, **k: answer("8.8.8.8")) == "8.8.8.8"
    for private in ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::1", "fd00::1"]:
        assert (
            resolve_public_address(destination, lambda *a, value=private, **k: answer(value))
            is None
        )
    assert (
        resolve_public_address(destination, lambda *a, **k: answer("8.8.8.8") + answer("10.0.0.1"))
        is None
    )


@pytest.mark.parametrize(
    "destination,status,expected",
    [
        ("hubspot", 201, "delivered"),
        ("hubspot", 401, "failed"),
        ("hubspot", 500, "uncertain"),
        ("hubspot", 302, "uncertain"),
        ("hubspot", 200, "uncertain"),
        ("automation", 202, "delivered"),
        ("automation", 400, "uncertain"),
        ("automation", 429, "uncertain"),
    ],
)
def test_status_semantics_and_no_terminal_resend(integration, destination, status, expected):
    _, settings, factory = integration
    item = queue(integration, destination)
    sends = []

    def sender(config, attempt, timeout):
        sends.append(attempt.id)
        return status

    assert worker.dispatch(factory, settings, item["id"], 0, sender=sender)
    with factory() as session:
        assert session.get(IntegrationDelivery, item["id"]).status == expected
    assert not worker.dispatch(factory, settings, item["id"], 1, sender=sender)
    assert len(sends) == 1


def test_ambiguous_timeout_never_retries(integration):
    _, settings, factory = integration
    item = queue(integration)

    def sender(*args):
        raise httpx.ReadTimeout("never print contact or secret")

    assert worker.dispatch(factory, settings, item["id"], 0, sender=sender)
    with factory() as session:
        row = session.get(IntegrationDelivery, item["id"])
        assert row.status == "uncertain" and row.error_code == "response_unknown"


def test_hubspot_rate_limit_retry_is_delayed_and_bounded(integration):
    _, settings, factory = integration
    item = queue(integration)
    now = datetime.now(UTC)

    def sender(*args):
        return 429

    assert worker.dispatch(factory, settings, item["id"], 0, sender=sender, now=now)
    assert not worker.dispatch(factory, settings, item["id"], 1, sender=sender, now=now)
    assert worker.dispatch(
        factory, settings, item["id"], 1, sender=sender, now=now + timedelta(seconds=61)
    )
    assert worker.dispatch(
        factory, settings, item["id"], 2, sender=sender, now=now + timedelta(seconds=182)
    )
    with factory() as session:
        row = session.get(IntegrationDelivery, item["id"])
        assert row.status == "failed" and row.attempt_count == 3


def test_two_workers_cannot_send_the_same_intent(integration):
    _, settings, factory = integration
    item = queue(integration)
    entered, release = Event(), Event()

    def sender(*args):
        entered.set()
        assert release.wait(5)
        return 201

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(worker.dispatch, factory, settings, item["id"], 0, sender=sender)
        assert entered.wait(5)
        try:
            assert not worker.dispatch(factory, settings, item["id"], 0, sender=sender)
        finally:
            release.set()
        assert first.result(5)


def test_crash_after_remote_send_becomes_uncertain_and_fences_late_results(
    integration, monkeypatch
):
    _, settings, factory = integration
    item = queue(integration)
    now = datetime.now(UTC)
    original = worker.finish

    def fail_finish(*args):
        raise OperationalError("test", {}, Exception("offline"))

    monkeypatch.setattr(worker, "finish", fail_finish)
    with pytest.raises(OperationalError):
        worker.dispatch(factory, settings, item["id"], 0, sender=lambda *args: 201, now=now)
    assert worker.recover_stale(factory, now + timedelta(seconds=121)) == 1
    assert worker.recover_stale(factory, now + timedelta(seconds=122)) == 0
    attempt = worker.Attempt(item["id"], 1, "hubspot", "key", "fingerprint", {})
    assert not original(factory, attempt, "delivered", None, now)
    with factory() as session:
        assert session.get(IntegrationDelivery, item["id"]).status == "uncertain"


@pytest.mark.parametrize("change", ["config", "location"])
def test_changed_configuration_or_location_prevents_sending(integration, change):
    _, settings, factory = integration
    item = queue(integration)
    if change == "config":
        settings.hubspot_access_token = "rotated-to-different-account"
    else:
        with factory() as session:
            session.get(Location, 1).active = False
            session.commit()

    def forbidden(*args):
        pytest.fail("must not call vendor")

    assert worker.dispatch(factory, settings, item["id"], 0, sender=forbidden)
    with factory() as session:
        assert session.get(IntegrationDelivery, item["id"]).status == "failed"


def test_explicit_api_send_requires_confirmation_and_uses_verified_actor(integration, monkeypatch):
    client, _, factory = integration
    item = queue(integration)
    original = worker.dispatch

    def mocked(*args, **kwargs):
        return original(*args, **kwargs, sender=lambda *args: 201)

    monkeypatch.setattr(api, "dispatch", mocked)
    path = f"/api/console/integrations/deliveries/{item['id']}/send"
    assert client.post(path, json={}).status_code == 422
    body = {"confirm_delivery": True, "expected_attempt_count": 0}
    assert client.post(path, json=body).json()["status"] == "delivered"
    assert client.post(path, json=body).status_code == 409
    with factory() as session:
        event = session.scalar(select(WorkflowAudit).where(WorkflowAudit.action == "sending"))
        assert event.actor == "owner"


def test_cli_defaults_to_dry_run(integration, monkeypatch, capsys):
    _, settings, factory = integration
    item = queue(integration)
    monkeypatch.setattr(worker, "get_settings", lambda: settings)

    def forbidden(*args, **kwargs):
        pytest.fail("dry run must not dispatch")

    monkeypatch.setattr(worker, "dispatch", forbidden)
    assert worker.main([]) == 0
    assert "dry_run" in capsys.readouterr().out
    with factory() as session:
        assert session.get(IntegrationDelivery, item["id"]).status == "queued"


def test_http_sender_pins_validated_ip_and_sni_without_reading_body(integration, monkeypatch):
    _, settings, _ = integration
    config = configured_destination(settings, "hubspot")
    attempt = worker.Attempt(
        1,
        1,
        "hubspot",
        "delivery-key",
        config.fingerprint,
        {"contact": {"name": "Fictional", "phone": "+12025550123"}},
    )
    real_client = httpx.Client
    observed = []

    def transport(request):
        observed.append(request)
        assert request.url.host == "8.8.8.8"
        assert request.headers["host"] == "api.hubapi.com"
        assert request.extensions["sni_hostname"] == "api.hubapi.com"
        assert request.headers["Idempotency-Key"] == "delivery-key"
        return httpx.Response(302, headers={"Location": "http://127.0.0.1"}, content=b"secret echo")

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return real_client(**kwargs, transport=httpx.MockTransport(transport))

    monkeypatch.setattr(worker, "resolve_public_address", lambda config: "8.8.8.8")
    monkeypatch.setattr(worker.httpx, "Client", client)
    assert worker.send_http(config, attempt, 3) == 302
    assert len(observed) == 1


def test_dns_timeout_fails_closed_and_is_bounded(monkeypatch):
    destination = configured_destination(SimpleNamespace(hubspot_access_token="secret"), "hubspot")

    def stalled(args, **kwargs):
        assert kwargs["timeout"] == 2 and kwargs["check"] is True
        assert args[-1] == "api.hubapi.com"
        raise subprocess.TimeoutExpired(args, 2)

    monkeypatch.setattr(service.subprocess, "run", stalled)
    assert resolve_public_address(destination) is None


def test_pre_send_dns_failure_can_retry_but_never_without_limit(integration):
    _, settings, factory = integration
    item = queue(integration)
    now = datetime.now(UTC)

    def unavailable(*args):
        raise worker.DestinationUnavailable()

    for attempt, seconds in enumerate([0, 61, 182]):
        assert worker.dispatch(
            factory,
            settings,
            item["id"],
            attempt,
            sender=unavailable,
            now=now + timedelta(seconds=seconds),
        )
    with factory() as session:
        row = session.get(IntegrationDelivery, item["id"])
        assert row.status == "failed" and row.attempt_count == 3


def test_delivery_exposes_only_concrete_contact_confirmation(integration):
    item = queue(integration)
    assert item["contact_name"] == "Fictional Person"
    assert item["contact_phone"] == "+12025550123"
    assert "payload" not in item and "config_fingerprint" not in item


def test_queue_uses_latest_corrected_contact_when_historical_duplicates_exist(integration):
    _, _, factory = integration
    with factory() as session:
        session.add(Lead(call_id=1, name="Latest approved name", callback_number="+12025550124"))
        session.commit()
    item = queue(integration)
    assert item["contact_name"] == "Latest approved name"
    assert item["contact_phone"] == "+12025550124"
