"""Storage visibility is bounded, read-only and authenticated before database work."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from arcagent.config import Settings, get_settings
from arcagent.console.storage import router
from arcagent.persistence.db import get_engine, session_scope
from arcagent.persistence.models import Base, Call, Speaker, Turn


@pytest.fixture
def storage_client(tmp_path):
    url = f"sqlite:///{tmp_path / 'storage.db'}"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    settings = Settings(_env_file=None, database_url=url, console_api_token="fixture")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client, settings
    engine.dispose()


def read(client, limit=1000):
    return client.get(
        f"/api/console/storage?limit={limit}", headers={"Authorization": "Bearer fixture"}
    )


def test_storage_authentication_precedes_database_work(storage_client, monkeypatch):
    client, _ = storage_client

    def forbidden(*args, **kwargs):
        raise AssertionError("Unauthenticated request opened database")

    monkeypatch.setattr("arcagent.console.storage.session_scope", forbidden)
    assert client.get("/api/console/storage").status_code == 401
    assert (
        client.get("/api/console/storage", headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )


def test_preview_counts_only_bounded_expired_content_and_never_returns_pii(storage_client):
    client, settings = storage_client
    with session_scope(settings.database_url) as session:
        old = datetime.now(UTC) - timedelta(days=90)
        call = Call(twilio_call_sid="private-sid", from_number_hash="private-hash", ended_at=old)
        session.add(call)
        session.flush()
        session.add_all(
            [
                Turn(call_id=call.id, turn_index=i, speaker=Speaker.CALLER, text="private")
                for i in range(4)
            ]
        )
    response = read(client, limit=3)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["database"]["available"] is True
    assert data["retention"]["candidate_turns"] == 3
    assert data["retention"]["candidate_calls"] == 1
    assert data["retention"]["candidate_text_characters"] == 21
    assert data["retention"]["has_more"] is True
    assert data["automation"] == "manual_only"
    assert data["physical_storage_bytes"] is None
    assert "private" not in response.text
    with session_scope(settings.database_url) as session:
        assert session.scalar(select(func.count(Turn.id)).where(Turn.text == "private")) == 4


def test_database_failure_is_unavailable_not_empty(storage_client, monkeypatch):
    client, _ = storage_client

    def unavailable(*args, **kwargs):
        raise OperationalError("private-query", {}, Exception("private-secret"))

    monkeypatch.setattr("arcagent.console.storage.session_scope", unavailable)
    response = read(client)
    assert response.status_code == 200
    assert response.json()["database"] == {"available": False}
    assert response.json()["retention"] is None
    assert "private" not in response.text


@pytest.mark.parametrize("limit", [0, 1001, -1])
def test_invalid_preview_limit_is_rejected(storage_client, limit):
    client, _ = storage_client
    assert read(client, limit).status_code == 422
