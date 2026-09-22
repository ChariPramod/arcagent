"""Controlled integration: real session, graph, routing and SQL writes; fake vendors."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from arcagent.agent.graph import AgentConfig
from arcagent.agent.responder import GraphResponder
from arcagent.app import _finish_call
from arcagent.config import Settings
from arcagent.persistence.db import get_engine, session_scope
from arcagent.persistence.models import Base, Call, Callback, Lead, LeadScore, Outcome, Slot, Turn
from arcagent.telephony.availability import CoordinatorAvailability
from arcagent.telephony.persistence_sink import DatabaseTurnSink
from arcagent.telephony.twilio_actions import TwilioActions
from tests.fakes import mark_message, start_message
from tests.harness import build_harness
from tests.test_graph_transitions import MockLLM
from tests.test_routing import FakeTwilioClient


@pytest.mark.parametrize(
    ("available", "reject_transfer", "disconnect", "expected"),
    [
        (True, False, False, None),
        (True, True, False, None),
        (False, False, False, Outcome.CALLBACK_BOOKED),
        (True, False, True, Outcome.ABANDONED),
    ],
)
async def test_controlled_call_persists_actual_routing_outcome(
    tmp_path, monkeypatch, ready_prompts, available, reject_transfer, disconnect, expected
):
    url = f"sqlite:///{tmp_path / 'controlled.db'}"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    settings = Settings(
        _env_file=None,
        database_url=url,
        deepgram_api_key="test",
        cartesia_api_key="test",
        cartesia_voice_id="test",
        coordinator_number="+15550001111",
        twilio_number="+15550002222",
        twilio_account_sid="AC_test",
        twilio_auth_token="test",
        public_url="https://voice.example.test",
    )
    start = start_message()
    start["start"]["customParameters"] = {"from": "+15550000123"}
    monkeypatch.setattr("tests.harness._start", lambda: start)

    class PersistedBeforeTransferClient(FakeTwilioClient):
        def calls(self, sid):
            # This runs inside the actual transfer action, before accepting/rejecting it.
            with session_scope(url) as db:
                lead = db.scalar(select(Lead))
                assert lead is not None, "Transfer attempted before lead was committed"
                assert db.scalar(select(LeadScore).where(LeadScore.lead_id == lead.id)) is not None
            return super().calls(sid)

    client = PersistedBeforeTransferClient(fail_calls=reject_transfer)
    monkeypatch.setattr(
        "arcagent.telephony.routing.TwilioActions", lambda config: TwilioActions(config, client)
    )
    llm = MockLLM(
        [
            {"next_utterance": "Understood.", "treatment_interest": "full_arch"},
            {"next_utterance": "Understood.", "pain_level": 8},
            {"next_utterance": "Understood.", "has_insurance": True},
            {
                "next_utterance": "Understood.",
                "name": "Fictional Caller",
                "callback_number": "5550000123",
            },
        ]
    )
    responder = GraphResponder(AgentConfig(llm=llm, coordinator_available=available))
    harness = build_harness(responder, settings=settings)
    sink = DatabaseTurnSink(url)
    harness.session.on_start = sink.open
    harness.session.turn_sink = sink
    acknowledgements: set[str] = set()

    async def playback_acknowledger():
        while True:
            for mark in harness.twilio.sent_of("mark"):
                name = mark["mark"]["name"]
                if name not in acknowledgements:
                    acknowledgements.add(name)
                    harness.twilio.push(mark_message(name))
            await asyncio.sleep(0.001)

    async def wait_for(predicate):
        async with asyncio.timeout(5):
            for _ in range(5000):
                if predicate():
                    return
                await asyncio.sleep(0.001)
            raise AssertionError("Controlled workflow did not reach expected state")

    with session_scope(url) as db:
        db.add(
            Slot(
                slot_start=datetime.now(UTC) + timedelta(days=1),
                slot_end=datetime.now(UTC) + timedelta(days=1, minutes=30),
                booked=False,
            )
        )
    ack_task = asyncio.create_task(playback_acknowledger())
    try:
        await harness.start()
        await wait_for(lambda: sink.call_id is not None and sink.turn_index >= 1)
        for index, text in enumerate(
            [
                "I want full arch treatment",
                "My pain is eight",
                "I have insurance",
                "My name is Fictional Caller and my number is 5550000123",
            ]
        ):
            if disconnect and index == 1:
                break
            prior = sink.turn_index
            await harness.caller_says(text)
            await wait_for(lambda prior=prior: sink.turn_index >= prior + 2)
        if not disconnect:
            await wait_for(lambda: harness._task.done())
        await harness.stop()
        await _finish_call(
            settings, harness.session, responder, sink, CoordinatorAvailability(available)
        )
        with session_scope(url) as db:
            call = db.get(Call, sink.call_id)
            assert call.outcome is expected
            assert (call.ended_at is None) is (expected is None)
            assert call.from_number_hash and not call.from_number_hash.startswith("+")
            turns = list(db.scalars(select(Turn).where(Turn.call_id == call.id)))
            assert any(t.speaker.value == "caller" for t in turns)
            assert any(
                t.speaker.value == "agent" and t.playback_start_ms is not None for t in turns
            )
            leads = list(db.scalars(select(Lead).where(Lead.call_id == call.id)))
            if disconnect:
                assert leads == []
                assert client.call_updates == []
                assert client.messages_sent == []
            else:
                assert len(leads) == 1
                persisted_score = db.scalar(
                    select(LeadScore).where(LeadScore.lead_id == leads[0].id)
                )
                assert persisted_score.score == 65
                assert persisted_score.decision.value == ("handoff" if available else "callback")
                callbacks = list(
                    db.scalars(select(Callback).where(Callback.lead_id == leads[0].id))
                )
                assert len(callbacks) == (0 if available else 1)
                assert len(client.call_updates) == (1 if available and not reject_transfer else 0)
                assert len(client.messages_sent) == (0 if available else 1)
        if available and not disconnect and not reject_transfer:
            # REST acceptance above is deliberately unresolved. Only a signed
            # callback with bridge evidence makes this a confirmed handoff.
            from fastapi.testclient import TestClient
            from twilio.request_validator import RequestValidator

            from arcagent.app import app
            from arcagent.config import get_settings
            from arcagent.persistence.transfer_models import TransferAttempt

            with session_scope(url) as db:
                attempt = db.scalar(
                    select(TransferAttempt).where(TransferAttempt.call_id == sink.call_id)
                )
                path = f"/voice/transfer/{attempt.id}/action"
            body = {
                "AccountSid": settings.twilio_account_sid,
                "CallSid": sink.twilio_call_sid,
                "DialCallSid": "CA_controlled_child",
                "DialCallStatus": "completed",
                "DialBridged": "true",
            }
            signature = RequestValidator(settings.twilio_auth_token).compute_signature(
                settings.public_url + path, body
            )
            app.dependency_overrides[get_settings] = lambda: settings
            try:
                with TestClient(app) as http:
                    assert (
                        http.post(
                            path, data=body, headers={"X-Twilio-Signature": signature}
                        ).status_code
                        == 200
                    )
            finally:
                app.dependency_overrides.clear()
            with session_scope(url) as db:
                assert db.get(Call, sink.call_id).outcome is Outcome.HANDOFF
    finally:
        ack_task.cancel()
        await asyncio.gather(ack_task, return_exceptions=True)
        await harness.stop()
        engine.dispose()
