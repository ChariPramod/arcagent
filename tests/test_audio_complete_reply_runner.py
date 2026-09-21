"""Audio evaluations answer complete server replies, with transcript persistence checked."""

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

from arcagent.agent.llm import LLMResult
from arcagent.persistence.db import get_engine, session_scope
from arcagent.persistence.models import Base
from arcagent.persistence.repo import CallRepository
from evals.persona import Persona
from evals.run_audio import run_audio_scenario

GREETING = ["This is the automated assistant.", "How can we help?"]
TERMINAL = ["Thank you for answering.", "The call is complete."]


class CallerModel:
    def __init__(self):
        self.messages = []

    async def complete(self, system, messages, schema, model=None):
        self.messages.append(messages)
        if len(self.messages) > 1:
            raise AssertionError("caller model must not answer incomplete or terminal replies")
        return LLMResult(
            parsed=schema.model_validate({"utterance": "A full arch, please."}),
            ttft_s=0,
            total_s=0,
            raw="{}",
        )


class CallerSpeech:
    def __init__(self):
        self.texts = []

    async def synthesize(self, text):
        self.texts.append(text)
        yield SimpleNamespace(audio=bytes(160))


class EvaluationServerSocket:
    """External WebSocket peer persists each ACK, then publishes reply completion."""

    def __init__(self, database_url, *, completion=True, mismatch=False):
        self.database_url = database_url
        self.completion = completion
        self.mismatch = mismatch
        self.inbox = asyncio.Queue()
        self.call_id = None
        self.terminal_sent = False
        self.acknowledged = []
        self.turn_index = 0

    def emit(self, frame):
        self.inbox.put_nowait(json.dumps(frame))

    def emit_reply(self, texts, prefix):
        for index, _text in enumerate(texts):
            self.emit(
                {"event": "media", "media": {"payload": base64.b64encode(bytes(160)).decode()}}
            )
            self.emit({"event": "mark", "mark": {"name": f"{prefix}-{index}"}})

    async def send(self, raw):
        message = json.loads(raw)
        if message["event"] == "start":
            with session_scope(self.database_url) as db:
                self.call_id = CallRepository(db).start_call(message["start"]["callSid"], "").id
            self.emit_reply(GREETING, "greeting")
        elif message["event"] == "mark":
            name = message["mark"]["name"]
            prefix, index = name.split("-")
            texts = GREETING if prefix == "greeting" else TERMINAL
            with session_scope(self.database_url) as db:
                repo = CallRepository(db)
                repo.add_turn(
                    self.call_id,
                    self.turn_index,
                    "agent",
                    "private-patient-secret" if self.mismatch else texts[int(index)],
                )
                self.turn_index += 1
                if prefix == "terminal" and index == "1":
                    repo.end_call(self.call_id, "handoff", final_node="audio_eval:end_call")
            self.acknowledged.append(name)
            if index == "1" and self.completion:
                self.emit(
                    {
                        "event": "eval.reply_complete",
                        "reply": {
                            "texts": texts,
                            "terminal": prefix == "terminal",
                            **({"fields": {"name": "Pat"}} if prefix == "terminal" else {}),
                        },
                    }
                )
        elif message["event"] == "media" and not self.terminal_sent:
            self.terminal_sent = True
            self.emit_reply(TERMINAL, "terminal")

    async def close(self):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.inbox.get()


@pytest.mark.timeout(5)
@pytest.mark.parametrize(
    "failure", [None, "missing_completion", "transcript_mismatch", "wrong_outcome", "wrong_field"]
)
async def test_runner_waits_for_complete_reply_and_never_answers_terminal_reply(
    tmp_path, monkeypatch, failure
):
    url = f"sqlite:///{tmp_path / 'reply.db'}"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    peer = EvaluationServerSocket(
        url, completion=failure != "missing_completion", mismatch=failure == "transcript_mismatch"
    )
    model = CallerModel()
    speech = CallerSpeech()

    async def connect(*args, **kwargs):
        return peer

    monkeypatch.setattr("websockets.connect", connect)
    monkeypatch.setattr("evals.run_audio.session_scope", lambda: session_scope(url))
    persona = Persona(
        id="complete_reply",
        group="hot_buyers",
        description="Synthetic protocol fixture",
        background="A fictional caller.",
        expected={
            "outcome": "callback_booked" if failure == "wrong_outcome" else "handoff",
            "handoff": failure != "wrong_outcome",
            "fields": {"name": "Alex" if failure == "wrong_field" else "Pat"},
        },
    )
    try:
        result = await run_audio_scenario(
            persona,
            "ws://localhost/eval/voice/stream",
            speech,
            model,
            caller_voice_id="fixture",
            auth_token="fixture",
            agent_wait_s=0.1,
            persistence_wait_s=0.1,
        )
        if failure in {"missing_completion", "transcript_mismatch"}:
            assert result.error is not None
            assert "private-patient-secret" not in result.error
            assert model.messages == []
            assert speech.texts == []
        else:
            assert result.error is None
            assert result.outcome == "handoff"
            assert result.passed is (failure is None)
            assert result.actual_fields == {"name": "Pat"}
            assert result.turns == 1
            assert [[item["content"] for item in messages] for messages in model.messages] == [
                GREETING
            ]
            assert speech.texts == ["A full arch, please."]
            assert peer.acknowledged == ["greeting-0", "greeting-1", "terminal-0", "terminal-1"]
    finally:
        engine.dispose()
