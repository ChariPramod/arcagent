"""Media stream session loops.

T2 ships the echo loop, which proves framing and encoding are right before STT or TTS
touch the audio. Later tasks add the real pipeline alongside it and keep the echo loop for
diagnosing a call where audio is wrong.
"""

from __future__ import annotations

from typing import Any, Protocol

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from arcagent.logging import get_logger
from arcagent.telephony.twilio_stream import (
    MarkEvent,
    MediaEvent,
    StartEvent,
    StopEvent,
    StreamSession,
    TwilioFrameError,
    build_media_message,
    parse_event,
)

log = get_logger(__name__)


class MediaSocket(Protocol):
    """The slice of a Starlette WebSocket this module uses.

    Narrow on purpose: the tests substitute a scripted socket with no server running.
    """

    async def receive_json(self) -> dict[str, Any]: ...

    async def send_json(self, data: dict[str, Any]) -> None: ...


class SocketClosed(Exception):
    """Raised by a socket implementation when the peer has gone away."""


class TwilioWebSocket:
    """Adapts a Starlette WebSocket to :class:`MediaSocket`.

    Starlette signals a hung up call with :class:`WebSocketDisconnect`, or with a
    ``RuntimeError`` if the socket was already closed. Both mean the same thing to the
    session loop, so both become :class:`SocketClosed`.
    """

    __slots__ = ("_ws",)

    def __init__(self, websocket: WebSocket) -> None:
        self._ws = websocket

    async def receive_json(self) -> dict[str, Any]:
        try:
            return await self._ws.receive_json()
        except (WebSocketDisconnect, RuntimeError) as exc:
            raise SocketClosed from exc

    async def send_json(self, data: dict[str, Any]) -> None:
        if self._ws.client_state is not WebSocketState.CONNECTED:
            raise SocketClosed
        try:
            await self._ws.send_json(data)
        except (WebSocketDisconnect, RuntimeError) as exc:
            raise SocketClosed from exc


async def run_echo_session(socket: MediaSocket) -> StreamSession:
    """Read Twilio events and send every inbound media frame straight back.

    Returns the session so a caller, or a test, can assert on the frame counts.
    """
    session = StreamSession()
    try:
        await _echo_loop(socket, session)
    except SocketClosed:
        log.info("stream_socket_closed", call_sid=session.call_sid)
    return session


async def _echo_loop(socket: MediaSocket, session: StreamSession) -> None:
    while True:
        message = await socket.receive_json()

        try:
            event = parse_event(message)
        except TwilioFrameError as exc:
            log.warning("twilio_frame_unparsed", error=str(exc))
            continue

        match event:
            case StartEvent():
                session.on_start(event)
                log.info(
                    "stream_started",
                    call_sid=event.call_sid,
                    encoding=event.encoding,
                    sample_rate=event.sample_rate,
                )
            case MediaEvent():
                session.on_media(event)
                await socket.send_json(build_media_message(session.stream_sid, event.payload))
                session.note_sent_frames(1)
            case MarkEvent():
                session.on_mark(event)
            case StopEvent():
                session.on_stop(event)
                log.info(
                    "stream_stopped",
                    call_sid=session.call_sid,
                    inbound_frames=session.inbound_frames,
                    outbound_frames=session.outbound_frames,
                )
                break
            case _:
                pass
