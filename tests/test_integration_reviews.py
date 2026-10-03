"""Operator evidence must never resend contacts or overwrite provider truth."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.exc import OperationalError

from arcagent.integrations import api, worker
from arcagent.integrations.reviews import record_review
from arcagent.persistence.integration_models import IntegrationDelivery, IntegrationReview
from arcagent.persistence.workflow_models import WorkflowAudit
from tests.test_integrations import integration as integration_fixture
from tests.test_integrations import queue

integration = integration_fixture

BASE = "/api/console/integrations/deliveries"


def terminal(integration, status="uncertain"):
    row = queue(integration)
    with integration[2]() as session:
        delivery = session.get(IntegrationDelivery, row["id"])
        delivery.status = status
        delivery.attempt_count = 1
        session.commit()
    return row["id"]


def body(**overrides):
    return {
        "client_request_id": str(uuid4()),
        "expected_status": "uncertain",
        "expected_attempt_count": 1,
        "expected_review_revision": 0,
        "resolution": "verified_received",
        "evidence": "Operator checked external contact reference SYNTHETIC-ONLY",
        **overrides,
    }


def test_review_keeps_provider_state_and_snapshot_audits_without_evidence(integration, monkeypatch):
    client, _, factory = integration
    identifier = terminal(integration)
    monkeypatch.setattr(worker, "send_http", lambda *_: pytest.fail("Must not send"))
    request = body(evidence="  Operator checked fictional receipt  ")
    response = client.post(f"{BASE}/{identifier}/reviews", json=request)
    assert response.status_code == 201, response.text
    assert response.json()["evidence"] == "Operator checked fictional receipt"
    assert response.json()["review_revision"] == 1
    assert response.json()["created_by"] == "owner"
    assert response.headers["cache-control"] == "no-store"
    with factory() as session:
        delivery = session.get(IntegrationDelivery, identifier)
        assert delivery.status == "uncertain" and delivery.attempt_count == 1
        assert delivery.review_revision == 1
        assert delivery.payload["contact"]["phone"] == "+12025550123"
        audit = session.scalar(select(WorkflowAudit).where(WorkflowAudit.action == "reviewed"))
        assert audit.changes["resolution"] == "verified_received"
        assert "evidence" not in audit.changes
        assert audit.actor == "owner"
    listing = client.get(BASE).json()["items"][0]
    assert listing["latest_review"] == response.json()
    assert listing["status"] == "uncertain"
    assert (
        client.post(
            f"{BASE}/{identifier}/send",
            json={"confirm_delivery": True, "expected_attempt_count": 1},
        ).status_code
        == 409
    )


def test_review_idempotency_and_append_only_revision(integration):
    client, _, factory = integration
    identifier = terminal(integration)
    request = body()
    first = client.post(f"{BASE}/{identifier}/reviews", json=request)
    retry = client.post(f"{BASE}/{identifier}/reviews", json=request)
    assert retry.status_code == 200 and retry.json() == first.json()
    assert (
        client.post(
            f"{BASE}/{identifier}/reviews", json={**request, "evidence": "different"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"{BASE}/{identifier}/reviews", json=request, headers={"X-Arcagent-Actor": "another"}
        ).status_code
        == 409
    )
    assert client.post(f"{BASE}/{identifier}/reviews", json=body()).status_code == 409
    second = client.post(
        f"{BASE}/{identifier}/reviews",
        json=body(expected_review_revision=1, resolution="needs_followup"),
    )
    assert second.status_code == 201
    # Lost-response replay still returns original, even after a later review.
    assert client.post(f"{BASE}/{identifier}/reviews", json=request).json() == first.json()
    history = client.get(f"{BASE}/{identifier}/reviews?limit=1").json()
    assert history["total"] == 2 and len(history["items"]) == 1
    assert history["items"][0] == second.json()
    assert client.get(f"{BASE}/{identifier}/reviews?limit=1&offset=1").json()["items"] == [
        first.json()
    ]
    with factory() as session:
        assert session.scalar(select(func.count(IntegrationReview.id))) == 2
        assert (
            session.scalar(
                select(func.count(WorkflowAudit.id)).where(WorkflowAudit.action == "reviewed")
            )
            == 2
        )


@pytest.mark.parametrize("status", ["queued", "sending", "delivered"])
def test_active_or_confirmed_delivery_cannot_be_reviewed(integration, status):
    identifier = terminal(integration, status)
    response = integration[0].post(f"{BASE}/{identifier}/reviews", json=body())
    assert response.status_code == 409
    with integration[2]() as session:
        assert session.scalar(select(func.count(IntegrationReview.id))) == 0
        assert session.get(IntegrationDelivery, identifier).review_revision == 0


@pytest.mark.parametrize(
    "change",
    [
        {"expected_attempt_count": 2},
        {"expected_status": "failed"},
        {"expected_review_revision": 1},
    ],
)
def test_stale_state_is_rejected(integration, change):
    identifier = terminal(integration)
    assert (
        integration[0].post(f"{BASE}/{identifier}/reviews", json=body(**change)).status_code == 409
    )


@pytest.mark.parametrize(
    "change",
    [
        {"evidence": " "},
        {"evidence": "SECRET" * 1000},
        {"expected_status": "sending"},
        {"resolution": "delivered"},
        {"client_request_id": "SECRET-INVALID"},
        {"unexpected": "SECRET"},
    ],
)
def test_validation_never_echoes_sensitive_body(integration, change):
    identifier = terminal(integration)
    response = integration[0].post(f"{BASE}/{identifier}/reviews", json=body(**change))
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid integration request"}
    assert response.headers["cache-control"] == "no-store"


def test_failed_delivery_can_be_human_reviewed_without_claiming_provider_success(integration):
    identifier = terminal(integration, "failed")
    response = integration[0].post(
        f"{BASE}/{identifier}/reviews", json=body(expected_status="failed")
    )
    assert response.status_code == 201
    assert response.json()["provider_status"] == "failed"
    assert integration[0].get(BASE).json()["items"][0]["status"] == "failed"


def test_authorization_and_missing_record(integration):
    client, _, _ = integration
    identifier = terminal(integration)
    assert (
        client.post(
            f"{BASE}/{identifier}/reviews", json=body(), headers={"Authorization": ""}
        ).status_code
        == 401
    )
    assert (
        client.post(
            f"{BASE}/{identifier}/reviews", json=body(), headers={"X-Arcagent-Actor": ""}
        ).status_code
        == 401
    )
    assert (
        client.get(f"{BASE}/{identifier}/reviews", headers={"Authorization": ""}).status_code == 401
    )
    assert client.post(f"{BASE}/999/reviews", json=body()).status_code == 404
    assert client.get(f"{BASE}/999/reviews").status_code == 404


def test_atomic_audit_failure_rolls_back_review_and_revision(integration):
    identifier = terminal(integration)
    factory = integration[2]
    with factory() as session:

        def reject_audit(session, context, instances):
            if any(
                isinstance(row, WorkflowAudit) and row.action == "reviewed" for row in session.new
            ):
                raise OperationalError("private_statement", {}, Exception("private_evidence"))

        event.listen(session, "before_flush", reject_audit)
        with pytest.raises(Exception) as exc:
            record_review(session, identifier, api.ReviewIntent(**body()), "owner")
        assert exc.value.status_code == 503
        assert "private" not in str(exc.value)
    with factory() as session:
        assert session.get(IntegrationDelivery, identifier).review_revision == 0
        assert session.scalar(select(func.count(IntegrationReview.id))) == 0


def test_concurrent_reviews_have_single_revision_winner(integration):
    identifier = terminal(integration)
    factory = integration[2]
    barrier = Barrier(2)

    def write():
        with factory() as session:
            barrier.wait()
            try:
                result, _ = record_review(session, identifier, api.ReviewIntent(**body()), "owner")
                return result["review_revision"]
            except Exception as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: write(), range(2)))
    assert sorted(results) == [1, 409]
    with factory() as session:
        assert session.scalar(select(func.count(IntegrationReview.id))) == 1


def test_recovery_never_sends_and_fences_late_worker(integration, monkeypatch):
    client, _, factory = integration
    delivery = queue(integration)
    now = datetime.now(UTC)
    attempt = worker.claim(factory, delivery["id"], 0, now - timedelta(minutes=10), "worker")
    monkeypatch.setattr(worker, "send_http", lambda *_: pytest.fail("No outbound requests"))
    response = client.post(f"{BASE}/recover-stale", json={"confirm_recovery": True, "limit": 1})
    assert response.status_code == 200 and response.json() == {
        "recovered": 1,
        "external_requests": False,
    }
    assert (
        client.post(f"{BASE}/recover-stale", json={"confirm_recovery": True}).json()["recovered"]
        == 0
    )
    assert not worker.finish(factory, attempt, "delivered", None, now)
    with factory() as session:
        row = session.get(IntegrationDelivery, delivery["id"])
        assert row.status == "uncertain" and row.updated_by == "owner"
        audit = session.scalar(select(WorkflowAudit).where(WorkflowAudit.action == "uncertain"))
        assert audit.actor == "owner"
    assert client.post(f"{BASE}/{delivery['id']}/reviews", json=body()).status_code == 201


def test_recovery_respects_lease_auth_and_bounded_confirmation(integration):
    client, _, factory = integration
    delivery = queue(integration)
    worker.claim(factory, delivery["id"], 0, datetime.now(UTC), "worker")
    assert (
        client.post(f"{BASE}/recover-stale", json={"confirm_recovery": True}).json()["recovered"]
        == 0
    )
    for request in [{}, {"confirm_recovery": False}, {"confirm_recovery": True, "limit": 101}]:
        assert client.post(f"{BASE}/recover-stale", json=request).status_code == 422
    assert (
        client.post(
            f"{BASE}/recover-stale",
            json={"confirm_recovery": True},
            headers={"X-Arcagent-Actor": ""},
        ).status_code
        == 401
    )


def test_latest_review_list_has_constant_query_count(integration):
    client, _, factory = integration
    identifier = terminal(integration)
    client.post(f"{BASE}/{identifier}/reviews", json=body())
    queries = []
    engine = factory.kw["bind"]

    def capture(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = client.get(BASE)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result.status_code == 200 and len(queries) == 3
    assert result.json()["items"][0]["latest_review"]["review_revision"] == 1


def test_review_migration_roundtrip_preserves_existing_delivery(tmp_path):
    from sqlalchemy import create_engine

    from alembic import command
    from tests.test_migrations import _alembic_config

    url = f"sqlite:///{tmp_path / 'migration.db'}"
    config = _alembic_config(url)
    command.upgrade(config, "g05cf124de67")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO integration_deliveries (id,call_id,location_id,location_name,destination,client_request_id,status,attempt_count,payload,config_fingerprint,created_by,updated_by) VALUES (1,1,1,'Synthetic','hubspot','synthetic','uncertain',1,'{}','hash','owner','owner')"
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT status,review_revision FROM integration_deliveries")
        ).one() == ("uncertain", 0)
        assert "integration_reviews" in inspect(connection).get_table_names()
    command.downgrade(config, "g05cf124de67")
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT status FROM integration_deliveries")).scalar()
            == "uncertain"
        )
        assert "integration_reviews" not in inspect(connection).get_table_names()
    engine.dispose()


def test_review_request_identifier_cannot_move_to_another_delivery(integration):
    client, _, factory = integration
    identifier = terminal(integration)
    second = queue(integration, "automation")
    with factory() as session:
        row = session.get(IntegrationDelivery, second["id"])
        row.status, row.attempt_count = "uncertain", 1
        session.commit()
    request = body()
    assert client.post(f"{BASE}/{identifier}/reviews", json=request).status_code == 201
    assert client.post(f"{BASE}/{second['id']}/reviews", json=request).status_code == 409
    assert client.get(BASE).json()["items"][0]["latest_review"] is None


def test_recovery_is_bounded_and_does_not_change_other_queued_work(integration):
    client, _, factory = integration
    first = queue(integration)
    second = queue(integration, "automation")
    now = datetime.now(UTC) - timedelta(minutes=10)
    worker.claim(factory, first["id"], 0, now, "worker")
    worker.claim(factory, second["id"], 0, now, "worker")
    assert (
        client.post(f"{BASE}/recover-stale", json={"confirm_recovery": True, "limit": 1}).json()[
            "recovered"
        ]
        == 1
    )
    with factory() as session:
        assert session.get(IntegrationDelivery, first["id"]).status == "uncertain"
        assert session.get(IntegrationDelivery, second["id"]).status == "sending"


def test_invalid_json_never_echoes_partial_evidence(integration):
    response = integration[0].post(
        f"{BASE}/1/reviews",
        content='{"evidence":"SECRET-PARTIAL",',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert "SECRET" not in response.text
