"""Evaluation reply boundaries exercised over the WebSocket transport boundary."""

import asyncio
import base64
import json

import pytest

from evals.fake_twilio import FakeTwilioCall


def media(value=0xFF):
    return {"event": "media", "media": {"payload": base64.b64encode(bytes([value]) * 160).decode()}}


def mark(name):
    return {"event": "mark", "mark": {"name": name}}


def complete(texts, terminal=False):
    return {"event": "eval.reply_complete", "reply": {"texts": texts, "terminal": terminal}}


@pytest.fixture
def transport(monkeypatch):
    class Socket:
        def __init__(self):
            self.incoming = asyncio.Queue()
            self.sent = asyncio.Queue()

        def push(self, message):
            self.incoming.put_nowait(json.dumps(message))

        async def send(self, raw):
            await self.sent.put(json.loads(raw))

        async def close(self):
            pass

        def __aiter__(self):
            return self

        async def __anext__(self):
            raw = await self.incoming.get()
            if raw is None:
                raise StopAsyncIteration
            return raw

    socket = Socket()

    async def connect(*args, **kwargs):
        return socket

    monkeypatch.setattr("websockets.connect", connect)
    return socket


def client():
    return FakeTwilioCall("ws://localhost/eval/voice/stream", auth_token="fixture")


async def test_acknowledges_each_utterance_but_waits_for_whole_reply(transport):
    async with client() as call:
        pending = asyncio.create_task(call.wait_for_reply(wait_s=1))
        transport.push(media())
        transport.push(mark("first"))
        ack = await asyncio.wait_for(transport.sent.get(), 1)
        assert ack["mark"]["name"] == "first"
        assert not pending.done()
        transport.push(media(0x7F))
        transport.push(mark("second"))
        ack = await asyncio.wait_for(transport.sent.get(), 1)
        assert ack["mark"]["name"] == "second"
        assert not pending.done()
        transport.push(complete(["One", "Two"], terminal=True))
        reply = await pending
    assert reply.texts == ["One", "Two"]
    assert reply.terminal is True
    assert reply.frames == [bytes([0xFF]) * 160, bytes([0x7F]) * 160]


@pytest.mark.parametrize(
    "texts,terminal",
    [([], False), ([""], False), ([3], False), ("text", False), (["Hi"], "false"), (["Hi"], 0)],
)
async def test_malformed_completion_is_rejected(transport, texts, terminal):
    async with client() as call:
        transport.push(media())
        transport.push(mark("utterance"))
        transport.push(complete(texts, terminal))
        with pytest.raises(ValueError, match="completion"):
            await call.wait_for_reply(wait_s=1)


@pytest.mark.parametrize(
    "events", [[], [media()], [mark("empty")], [media(), mark("done"), media()]]
)
async def test_completion_requires_audio_fully_covered_by_marks(transport, events):
    async with client() as call:
        for message in events:
            transport.push(message)
        transport.push(complete(["Hi"]))
        with pytest.raises(ValueError, match="completion"):
            await call.wait_for_reply(wait_s=1)


async def test_clear_discards_accumulated_reply_before_replacement(transport):
    async with client() as call:
        for message in [
            media(),
            mark("old"),
            {"event": "clear"},
            media(0x7F),
            mark("new"),
            complete(["Replacement"]),
        ]:
            transport.push(message)
        reply = await call.wait_for_reply(wait_s=1)
        assert reply.frames == [bytes([0x7F]) * 160]
        assert reply.texts == ["Replacement"]
        assert call.cleared == 1


async def test_closed_stream_fails_promptly_before_complete_reply(transport):
    async with client() as call:
        transport.push(media())
        transport.push(mark("incomplete"))
        transport.incoming.put_nowait(None)
        with pytest.raises(ConnectionError):
            await call.wait_for_reply(wait_s=0.1)


async def test_missing_completion_times_out_even_after_mark(transport):
    async with client() as call:
        transport.push(media())
        transport.push(mark("incomplete"))
        with pytest.raises(TimeoutError):
            await call.wait_for_reply(wait_s=0.01)


async def test_duplicate_mark_does_not_certify_extra_utterance(transport):
    async with client() as call:
        for message in [media(), mark("same"), mark("same"), complete(["One", "Two"])]:
            transport.push(message)
        with pytest.raises(ValueError, match="completion"):
            await call.wait_for_reply(wait_s=1)


@pytest.mark.parametrize("reply", [None, [], {}, {"texts": ["Hi"]}])
async def test_completion_requires_a_structured_reply(transport, reply):
    async with client() as call:
        transport.push(media())
        transport.push(mark("one"))
        transport.push({"event": "eval.reply_complete", "reply": reply})
        with pytest.raises(ValueError, match="completion"):
            await call.wait_for_reply(wait_s=1)
