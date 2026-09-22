from fastapi import FastAPI
from fastapi.testclient import TestClient

from arcagent.config import Settings, get_settings
from arcagent.console.workbench import router


def test_replay_requires_auth_and_rejects_unbounded_or_unknown_scenarios():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, console_api_token="fixture"
    )
    client = TestClient(app)
    assert client.get("/api/console/lab/scenarios").status_code == 401
    headers = {"Authorization": "Bearer fixture"}
    catalog = client.get("/api/console/lab/scenarios", headers=headers)
    assert catalog.status_code == 200
    scenario = catalog.json()["items"][0]["id"]
    result = client.post("/api/console/lab/replay", headers=headers, json={"scenario_id": scenario})
    assert result.status_code == 200
    assert result.json()["simulated"] is True
    assert result.json()["baseline"]["passed"] is True
    assert (
        client.post(
            "/api/console/lab/replay", headers=headers, json={"scenario_id": "unknown"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/console/lab/replay",
            headers=headers,
            json={"scenario_id": scenario, "candidate_config": {"vendor_timeout_ms": -1}},
        ).status_code
        == 422
    )


def test_latency_report_and_call_ids_are_bounded(tmp_path):
    from datetime import UTC, datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from arcagent.console.api import database
    from arcagent.console.api import router as console_router
    from arcagent.persistence.models import Base, Call, Speaker, Turn

    engine = create_engine(f"sqlite:///{tmp_path / 'calls.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        call = Call(
            twilio_call_sid="fixture", from_number_hash="fictional", started_at=datetime.now(UTC)
        )
        session.add(call)
        session.flush()
        session.add(Turn(call_id=call.id, turn_index=0, speaker=Speaker.AGENT, llm_ttft_ms=120))
        session.commit()
        call_id = call.id

    app = FastAPI()
    app.include_router(router)
    app.include_router(console_router)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, console_api_token="fixture"
    )

    def db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[database] = db
    client = TestClient(app)
    headers = {"Authorization": "Bearer fixture"}
    result = client.get(f"/api/console/calls/{call_id}/latency", headers=headers)
    assert result.status_code == 200
    assert result.json()["caller_perceived_latency_ms"] is None
    assert result.json()["stages"][1]["p50_ms"] == 120
    assert result.json()["stages"][2]["p50_ms"] is None
    assert client.get("/api/console/calls/999/latency", headers=headers).status_code == 404
    for path in (
        "calls/999999999999999999999999/latency",
        "calls/999999999999999999999999",
        "evals/999999999999999999999999",
        "compare?before=999999999999999999999999&after=1",
    ):
        assert client.get(f"/api/console/{path}", headers=headers).status_code == 422
    engine.dispose()
