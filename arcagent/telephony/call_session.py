"""The live call loop: Twilio in, Deepgram, an agent, Cartesia, Twilio out.

Read docs/turn_taking.md first. This module implements that document; where the two
disagree the document is right and this file is a bug.
"""

from __future__ import annotations

import asyncio
import enum
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from arcagent.agent.edge_cases import SILENCE_GOODBYE, SILENCE_REPROMPT, SPANISH_FALLBACK
from arcagent.config import Settings
from arcagent.logging import get_logger
from arcagent.speech.cartesia_tts import CartesiaTTS
from arcagent.speech.deepgram_stt import (
    DeepgramSTT,
    SpeechStartedEvent,
    TranscriptEvent,
    UtteranceEndEvent,
)
from arcagent.telephony.latency import TurnTimings
from arcagent.telephony.session_handler import MediaSocket, SocketClosed
from arcagent.telephony.twilio_stream import (
    DtmfEvent,
    MarkEvent,
    MediaEvent,
    StartEvent,
    StopEvent,
    StreamSession,
    TwilioFrameError,
    build_clear_message,
    build_mark_message,
    build_media_message,
    chunk_audio,
    parse_event,
)

log = get_logger(__name__)

# How often the silence watchdog wakes. Small enough to be responsive, large enough not
# to spin. Injectable as `sleep` so tests can drive it with a fake clock.
SILENCE_POLL_S = 0.25

# Queued instead of a caller transcript when the session, rather than the caller, is what
# prompts the agent to speak. Compared by identity, never by value, so a caller saying the
# same words cannot trigger one. Each maps to a line spoken verbatim.
_FALLBACK_SENTINEL = "\x00language-fallback"
_REPROMPT_SENTINEL = "\x00silence-reprompt"
_GOODBYE_SENTINEL = "\x00silence-goodbye"

FIXED_LINES = {
    _FALLBACK_SENTINEL: SPANISH_FALLBACK,
    _REPROMPT_SENTINEL: SILENCE_REPROMPT,
    _GOODBYE_SENTINEL: SILENCE_GOODBYE,
}


class SessionState(enum.StrEnum):
    LISTENING = "listening"
    SPEAKING = "speaking"
    ENDING = "ending"


class Responder(Protocol):
    """What the audio loop needs from an agent.

    The parrot implements this in T4; the LangGraph agent implements it in T9. Returning an
    async iterator lets a streaming LLM start speech before the whole reply exists.
    """

    async def respond(self, transcript: str) -> AsyncIterator[str]: ...

    @property
    def node_name(self) -> str | None: ...

    @property
    def should_end(self) -> bool: ...


@dataclass(slots=True)
class TurnRecord:
    """One completed turn, handed to whatever persists it."""

    speaker: str
    text: str
    latency: dict[str, int | None] = field(default_factory=dict)
    interrupted: bool = False
    node_name: str | None = None


TurnSink = Callable[[TurnRecord], Awaitable[None]]
StartHook = Callable[[StartEvent], Awaitable[None]]


@dataclass(slots=True)
class _OutboundFrame:
    """One 20 ms frame, or a mark when ``audio`` is None."""

    context_id: str
    audio: bytes | None = None
    mark_name: str | None = None


class ParrotResponder:
    """Says back whatever it heard. Proves the audio path before the agent exists."""

    def __init__(self) -> None:
        self.node_name = "parrot"
        self.should_end = False

    async def respond(self, transcript: str) -> AsyncIterator[str]:
        yield transcript


class CallSession:
    """One inbound call.

    The constructor takes every collaborator so a test can drive a whole call with fakes
    and no network, no clock, and no database.
    """

    def __init__(
        self,
        socket: MediaSocket,
        stt: DeepgramSTT,
        tts: CartesiaTTS,
        responder: Responder,
        settings: Settings,
        turn_sink: TurnSink | None = None,
        on_start: StartHook | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.socket = socket
        self.stt = stt
        self.tts = tts
        self.responder = responder
        self.settings = settings
        self.turn_sink = turn_sink
        self.on_start = on_start
        self.clock = clock
        self.sleep = sleep

        self.stream = StreamSession()
        self.state = SessionState.LISTENING
        self.turn_index = 0
        self.turns: list[TurnRecord] = []
        self.reprompted = False
        self.barge_ins = 0

        self._outbound: asyncio.Queue[_OutboundFrame | None] = asyncio.Queue()
        self._caller_turns: asyncio.Queue[tuple[str, TurnTimings]] = asyncio.Queue()
        self._agent_task: asyncio.Task[None] | None = None
        self._discarded: set[str] = set()
        self._active_context: str | None = None
        self._spoken_so_far = ""
        self._pending_timings = TurnTimings(clock=self.clock)
        self._last_caller_activity = self.clock()
        self._done = asyncio.Event()

        # Spanish fallback: after the fixed message the caller keys their number, so the
        # session collects DTMF instead of transcripts until they press hash.
        self.dtmf_digits: list[str] = []
        self.awaiting_dtmf = False
        self.language_fallback = False
        self.outcome: str | None = None

    # ------------------------------------------------------------------ run

    async def run(self) -> None:
        """Drive the call until Twilio hangs up or a terminal path ends it."""
        loops = [
            ("reader", self._reader_loop),
            ("transcripts", self._transcript_loop),
            ("agent", self._agent_loop),
            ("writer", self._writer_loop),
            ("silence", self._silence_loop),
        ]
        try:
            async with asyncio.TaskGroup() as tasks:
                handles = [tasks.create_task(loop(), name=name) for name, loop in loops]
                await self._done.wait()
                for handle in handles:
                    handle.cancel()
        except* SocketClosed:
            log.info("call_socket_closed", call_sid=self.stream.call_sid)
        finally:
            self.state = SessionState.ENDING

    def end(self) -> None:
        """Ask every task to stop. Idempotent."""
        self.state = SessionState.ENDING
        self._done.set()

    # --------------------------------------------------------------- reader

    async def _reader_loop(self) -> None:
        while True:
            try:
                message = await self.socket.receive_json()
            except SocketClosed:
                self.end()
                return

            try:
                event = parse_event(message)
            except TwilioFrameError as exc:
                log.warning("twilio_frame_unparsed", error=str(exc))
                continue

            match event:
                case StartEvent():
                    self.stream.on_start(event)
                    log.info("call_started", call_sid=event.call_sid)
                    if self.on_start is not None:
                        try:
                            await self.on_start(event)
                        except Exception:
                            log.exception("on_start_failed", call_sid=event.call_sid)
                    # An empty transcript is the signal to greet. The caller has not
                    # spoken yet and must not have to before hearing the disclosure.
                    self._caller_turns.put_nowait(("", TurnTimings(clock=self.clock)))
                case MediaEvent():
                    self.stream.on_media(event)
                    self._pending_timings.mark_audio_frame()
                    await self.stt.send_audio(event.payload)
                case MarkEvent():
                    self.stream.on_mark(event)
                    self._pending_timings.mark_playback_started()
                    if not self.stream.is_playing and self.state is SessionState.SPEAKING:
                        self.state = SessionState.LISTENING
                        self._last_caller_activity = self.clock()
                case DtmfEvent():
                    log.info("dtmf", digit=event.digit)
                    if self.awaiting_dtmf:
                        if event.digit == "#":
                            log.info(
                                "dtmf_capture_complete",
                                call_sid=self.stream.call_sid,
                                digit_count=len(self.dtmf_digits),
                            )
                            self.end()
                            return
                        self.dtmf_digits.append(event.digit)
                case StopEvent():
                    self.stream.on_stop(event)
                    self.end()
                    return
                case _:
                    pass

    # ----------------------------------------------------------- transcripts

    async def _transcript_loop(self) -> None:
        async for event in self.stt:
            match event:
                case TranscriptEvent():
                    await self._on_transcript(event)
                case UtteranceEndEvent():
                    self._last_caller_activity = self.clock()
                case SpeechStartedEvent():
                    self._last_caller_activity = self.clock()
                case _:
                    pass

    async def _on_transcript(self, event: TranscriptEvent) -> None:
        if not event.text:
            return
        self._last_caller_activity = self.clock()

        if event.is_final and await self._check_language(event):
            return
        if self.awaiting_dtmf:
            return  # the caller is keying a number, not talking to the agent

        if self.state is SessionState.SPEAKING and self._should_barge_in(event):
            await self._barge_in()

        if event.is_final and event.speech_final:
            self._pending_timings.mark_stt_final(event.ts)
            timings = self._pending_timings
            self._pending_timings = TurnTimings(clock=self.clock)
            await self._record_turn(TurnRecord(speaker="caller", text=event.text))
            self._caller_turns.put_nowait((event.text, timings))

    async def _check_language(self, event: TranscriptEvent) -> bool:
        """Fall back to a Spanish callback when the caller is clearly not speaking English.

        The fixed message is spoken rather than generated, so it is identical every time,
        and the callback number arrives as keypad tones because the STT session is
        configured for English and would mis-transcribe spoken Spanish digits.
        """
        observe = getattr(self.responder, "observe_language", None)
        if observe is None or not event.language or not observe(event.language):
            return False

        self.language_fallback = True
        self.awaiting_dtmf = True
        log.info("language_fallback", call_sid=self.stream.call_sid)
        if self.state is SessionState.SPEAKING:
            await self._barge_in()
        self._caller_turns.put_nowait((_FALLBACK_SENTINEL, TurnTimings(clock=self.clock)))
        return True

    def _should_barge_in(self, event: TranscriptEvent) -> bool:
        """A final always interrupts. An interim only if it is more than a backchannel."""
        if event.is_final:
            return True
        return event.word_count >= self.settings.barge_in_min_words

    async def _barge_in(self) -> None:
        """Stop the agent talking. Steps and their order are docs/turn_taking.md."""
        context_id = self._active_context
        self.state = SessionState.LISTENING
        if context_id is not None:
            self._discarded.add(context_id)

        self._drain_outbound()
        if self.stream.stream_sid:
            await self.socket.send_json(build_clear_message(self.stream.stream_sid))
        self.stream.clear_pending_marks()

        task = self._agent_task
        self._agent_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        if context_id is not None:
            await self.tts.cancel(context_id)

        self.barge_ins += 1
        if self._spoken_so_far:
            await self._record_turn(
                TurnRecord(
                    speaker="agent",
                    text=self._spoken_so_far,
                    interrupted=True,
                    node_name=self.responder.node_name,
                )
            )
        self._spoken_so_far = ""
        self._active_context = None
        log.info("barge_in", call_sid=self.stream.call_sid, count=self.barge_ins)

    def _drain_outbound(self) -> None:
        while True:
            try:
                self._outbound.get_nowait()
            except asyncio.QueueEmpty:
                return

    # ----------------------------------------------------------------- agent

    async def _agent_loop(self) -> None:
        """Run one agent turn at a time, cancellable by barge in and by hangup.

        Cancellation needs care here. Cancelling a task that is awaiting another task does
        not raise inside it directly: asyncio delivers the cancellation to the task being
        awaited. So a hangup arrives looking exactly like a barge in, and the only reliable
        way to tell them apart is whether the call is ending.
        """
        while not self._done.is_set():
            transcript, timings = await self._caller_turns.get()
            if self._done.is_set():
                return
            task = asyncio.create_task(self._speak_reply(transcript, timings), name="agent-turn")
            self._agent_task = task
            try:
                await task
            except asyncio.CancelledError:
                task.cancel()
                if self._done.is_set() or not task.cancelled():
                    raise
                # Barge in cancelled this turn. The call continues with the next one.
            except Exception:
                log.exception("agent_turn_failed", call_sid=self.stream.call_sid)
            finally:
                if self._agent_task is task:
                    self._agent_task = None
            if self.responder.should_end:
                self.end()
                return

    async def _speak_reply(self, transcript: str, timings: TurnTimings) -> None:
        for sentinel, line in FIXED_LINES.items():
            if transcript is sentinel:
                try:
                    await self._speak(line, timings)
                finally:
                    # The goodbye ends the call, but only after it has been said. Ending
                    # from the silence watchdog instead cancels the writer before a single
                    # frame reaches Twilio. The finally is deliberate: a failure to
                    # synthesise must not leave a silent call open forever.
                    if transcript is _GOODBYE_SENTINEL:
                        self.end()
                return
        timings.mark_llm_start()
        async for text in self.responder.respond(transcript):
            timings.mark_llm_first_token()
            if not text.strip():
                continue
            await self._speak(text, timings)

    async def _speak(self, text: str, timings: TurnTimings) -> None:
        """Synthesise one utterance and queue it. Cancellation here is barge in."""
        context_id = self.tts.new_context_id()
        self._active_context = context_id
        self.state = SessionState.SPEAKING
        timings.mark_tts_request()

        leftover = b""
        try:
            async for chunk in self.tts.synthesize(text, context_id=context_id):
                timings.mark_tts_first_byte(chunk.ts)
                frames = chunk_audio(leftover + chunk.audio, pad=False)
                if frames and len(frames[-1]) < 160:
                    leftover = frames.pop()
                else:
                    leftover = b""
                for frame in frames:
                    self._outbound.put_nowait(_OutboundFrame(context_id, audio=frame))
            if leftover:
                self._outbound.put_nowait(
                    _OutboundFrame(context_id, audio=chunk_audio(leftover)[0])
                )
        except asyncio.CancelledError:
            raise

        mark_name = f"utt-{self.turn_index}-{context_id[:8]}"
        self.stream.note_sent_mark(mark_name)
        self._outbound.put_nowait(_OutboundFrame(context_id, mark_name=mark_name))
        self._spoken_so_far = text
        await self._record_turn(
            TurnRecord(
                speaker="agent",
                text=text,
                latency=timings.as_columns(),
                node_name=self.responder.node_name,
            )
        )

    # ---------------------------------------------------------------- writer

    async def _writer_loop(self) -> None:
        """The only task that writes audio to Twilio."""
        while True:
            item = await self._outbound.get()
            if item is None:
                return
            if item.context_id in self._discarded:
                continue
            if not self.stream.stream_sid:
                continue
            if item.audio is not None:
                await self.socket.send_json(build_media_message(self.stream.stream_sid, item.audio))
                self.stream.note_sent_frames(1)
                self._pending_timings.mark_first_frame_written()
            elif item.mark_name is not None:
                await self.socket.send_json(
                    build_mark_message(self.stream.stream_sid, item.mark_name)
                )

    # --------------------------------------------------------------- silence

    async def _silence_loop(self) -> None:
        while True:
            await self.sleep(SILENCE_POLL_S)
            if self.state is not SessionState.LISTENING:
                continue
            idle = self.clock() - self._last_caller_activity
            if idle >= self.settings.silence_hangup_s:
                log.info("silence_hangup", call_sid=self.stream.call_sid, idle_s=round(idle, 1))
                self.outcome = "abandoned"
                self._caller_turns.put_nowait((_GOODBYE_SENTINEL, TurnTimings(clock=self.clock)))
                # The agent loop ends the call once the goodbye has actually been spoken.
                return
            if idle >= self.settings.silence_reprompt_s and not self.reprompted:
                self.reprompted = True
                self._last_caller_activity = self.clock()
                self._caller_turns.put_nowait((_REPROMPT_SENTINEL, TurnTimings(clock=self.clock)))

    # ------------------------------------------------------------ turn sink

    async def _record_turn(self, record: TurnRecord) -> None:
        record_index = self.turn_index
        self.turn_index += 1
        self.turns.append(record)
        if self.turn_sink is not None:
            try:
                await self.turn_sink(record)
            except Exception:
                log.exception("turn_sink_failed", turn_index=record_index)
