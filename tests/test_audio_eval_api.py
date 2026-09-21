"""The isolated audio API exercises the real pipeline without making routing actions."""

import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from arcagent.app import app
from arcagent.config import Settings, get_settings
from arcagent.persistence.db import get_engine, get_session_factory, session_scope
from arcagent.persistence.models import Base, Call, Callback, Lead
from arcagent.telephony.availability import reset_availability
from tests.fakes import FakeSttSocket, FakeTtsSocket, dg_results, mark_message, start_message
from tests.test_graph_transitions import HOT_LEAD, MockLLM


@pytest.mark.timeout(10)
@pytest.mark.parametrize(
    ("threshold", "expected", "disconnect"),
    [
        (60, "handoff", False),
        (999, "callback_booked", False),
        (60, "abandoned", False),
        (60, "abandoned", "partial"),
        (60, "abandoned", "terminal"),
    ],
)
def test_audio_eval_completes_and_persists_simulation_without_external_actions(
    tmp_path, monkeypatch, threshold, expected, disconnect
):
    reset_availability()
    evaluation = expected != "abandoned"
    answer_count = 4 if evaluation or disconnect == "terminal" else 3
    database_url = f"sqlite:///{tmp_path / 'eval.db'}"
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    settings = Settings(
        _env_file=None,
        env="test",
        enable_audio_evals=True,
        audio_eval_token="test-eval-token",
        database_url=database_url,
        handoff_threshold=threshold,
        silence_reprompt_s=20 if evaluation or disconnect else 0.1,
        silence_hangup_s=25 if evaluation or disconnect else 0.2,
        validate_twilio_signature=evaluation,
    )
    monkeypatch.setattr("arcagent.persistence.db.get_settings", lambda: settings)
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    stt = FakeSttSocket()
    tts = FakeTtsSocket()
    model = MockLLM(HOT_LEAD)

    async def connect_stt(*args):
        return stt

    async def connect_tts(*args):
        return tts

    async def complete(self, *args, **kwargs):
        return await model.complete(*args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("evaluation attempted an external Twilio action")

    monkeypatch.setattr("arcagent.speech.deepgram_stt._default_connect", connect_stt)
    monkeypatch.setattr("arcagent.speech.cartesia_tts._default_connect", connect_tts)
    monkeypatch.setattr("arcagent.agent.llm.AnthropicStructuredLLM.complete", complete)
    monkeypatch.setattr("arcagent.telephony.twilio_actions.TwilioActions.warm_transfer", forbidden)
    monkeypatch.setattr(
        "arcagent.telephony.twilio_actions.TwilioActions.send_callback_sms", forbidden
    )
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            with client.websocket_connect(
                "/eval/voice/stream" if evaluation else "/voice/stream",
                headers={"Authorization": "Bearer test-eval-token"},
            ) as ws:
                ws.send_json(start_message())
                answers = iter(
                    [
                        "I need full arch implants",
                        "My teeth hurt a lot",
                        "Yes through work",
                        "Bob, 4155550123",
                    ]
                )
                answers_sent = 0
                while True:
                    message = ws.receive()
                    if message["type"] == "websocket.close":
                        assert message["code"] == 1000
                        break
                    frame = json.loads(message["text"])
                    if frame["event"] == "mark":
                        if disconnect and len(model.calls) == answer_count:
                            ws.close()
                            deadline = time.monotonic() + 2
                            while time.monotonic() < deadline:
                                with session_scope(database_url) as db:
                                    call = db.scalar(select(Call))
                                    if call is not None and call.ended_at is not None:
                                        break
                                time.sleep(0.01)
                            else:
                                pytest.fail("disconnected call was not finalized")
                            break
                        ws.send_json(mark_message(frame["mark"]["name"]))
                        if answers_sent < answer_count:
                            text = next(answers)
                            client.portal.call(
                                stt.push, dg_results(text, is_final=True, speech_final=True)
                            )
                            answers_sent += 1
        assert answers_sent == answer_count
        assert len(model.calls) == answer_count
        with session_scope(database_url) as db:
            call = db.scalar(select(Call))
            assert call is not None
            assert call.outcome == expected
            assert call.ended_at is not None
            assert call.final_node.startswith("audio_eval:") == evaluation
            assert db.scalar(select(func.count()).select_from(Lead)) == 0
            assert db.scalar(select(func.count()).select_from(Callback)) == 0
        assert stt.closed and tts.closed
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        get_session_factory.cache_clear()
        get_engine.cache_clear()
        reset_availability()
