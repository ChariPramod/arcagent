"""A whole call, driven with fakes: no sockets, no clock, no database.

Used by the parrot round trip and the barge in tests. The real DeepgramSTT, CartesiaTTS
and CallSession run; only the three sockets are substituted.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from arcagent.config import Settings
from arcagent.speech.cartesia_tts import CartesiaTTS
from arcagent.speech.deepgram_stt import DeepgramSTT
from arcagent.telephony.call_session import CallSession, ParrotResponder, Responder, TurnRecord
from tests.fakes import FakeMediaSocket, FakeSttSocket, FakeTtsSocket

FRAME = b"\xff" * 160


class ScriptedResponder:
    """Says whatever it is told to say next. Stands in for the LangGraph agent."""

    def __init__(self, replies: list[str] | None = None, node_name: str = "test_node") -> None:
        self.replies = list(replies or [])
        self.heard: list[str] = []
        self.node_name = node_name
        self.should_end = False

    async def respond(self, transcript: str) -> AsyncIterator[str]:
        if not transcript:
            return  # the greeting turn; a scripted responder has nothing to greet with
        self.heard.append(transcript)
        yield self.replies.pop(0) if self.replies else "acknowledged"


@dataclass
class CallHarness:
    settings: Settings
    twilio: FakeMediaSocket
    stt_socket: FakeSttSocket
    tts_socket: FakeTtsSocket
    session: CallSession
    turns: list[TurnRecord] = field(default_factory=list)
    _task: asyncio.Task | None = None

    async def start(self) -> None:
        await self.session.stt.start()
        await self.session.tts.start()
        self._task = asyncio.create_task(self.session.run(), name="call")
        self.twilio.push(_start())
        await self.settle()

    async def caller_says(
        self, text: str, is_final: bool = True, speech_final: bool = True
    ) -> None:
        """Push audio then the matching transcript, as a real call would."""
        from tests.fakes import dg_results, media_message

        self.twilio.push(media_message(FRAME))
        await self.settle()
        self.stt_socket.push(dg_results(text, is_final=is_final, speech_final=speech_final))
        await self.settle()

    async def settle(self, rounds: int = 60) -> None:
        """Let every task make whatever progress it can. There are no real timers here."""
        for _ in range(rounds):
            await asyncio.sleep(0)

    async def wait_until(self, predicate: Callable[[], bool], rounds: int = 400) -> bool:
        for _ in range(rounds):
            if predicate():
                return True
            await asyncio.sleep(0)
        return False

    async def stop(self) -> None:
        self.twilio.hangup()
        if self._task is not None:
            # A hangup must end the call promptly even mid utterance. A timeout here is a
            # real failure, not slow test infrastructure, so keep it short and loud.
            try:
                await asyncio.wait_for(self._task, timeout=2)
            except TimeoutError:
                self._task.cancel()
                raise AssertionError("call session did not shut down within 2s of hangup") from None
            except asyncio.CancelledError:
                self._task.cancel()
        await self.session.stt.close()
        await self.session.tts.close()


def build_harness(
    responder: Responder | None = None,
    tts_responses: list[list[bytes]] | None = None,
    tts_auto: bool = True,
    settings: Settings | None = None,
    clock: Callable[[], float] | None = None,
) -> CallHarness:
    """Build a call wired to fakes. With a ``clock`` the silence watchdog polls instantly,
    so a test advances the fake clock rather than waiting on a real timer."""
    settings = settings or Settings(
        _env_file=None,
        deepgram_api_key="dg_test",
        cartesia_api_key="ct_test",
        cartesia_voice_id="voice_test",
    )
    twilio = FakeMediaSocket(keep_open=True)
    stt_socket = FakeSttSocket()
    tts_socket = FakeTtsSocket(responses=tts_responses, auto=tts_auto)

    async def stt_connect(url: str, headers: dict[str, str]) -> FakeSttSocket:
        return stt_socket

    async def tts_connect(url: str, headers: dict[str, str]) -> FakeTtsSocket:
        return tts_socket

    turns: list[TurnRecord] = []

    async def sink(record: TurnRecord) -> None:
        turns.append(record)

    session = CallSession(
        socket=twilio,
        stt=DeepgramSTT(settings, connect=stt_connect),
        tts=CartesiaTTS(settings, connect=tts_connect),
        responder=responder or ParrotResponder(),
        settings=settings,
        turn_sink=sink,
        **({"clock": clock, "sleep": _instant_sleep} if clock else {}),
    )
    return CallHarness(
        settings=settings,
        twilio=twilio,
        stt_socket=stt_socket,
        tts_socket=tts_socket,
        session=session,
        turns=turns,
    )


async def _instant_sleep(_delay: float) -> None:
    """Collapses the silence watchdog's poll interval so a fake clock drives it."""
    await asyncio.sleep(0)


def _start() -> dict:
    from tests.fakes import start_message

    return start_message()
