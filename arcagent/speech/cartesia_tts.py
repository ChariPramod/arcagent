"""Cartesia streaming text to speech.

Cartesia is asked for raw mulaw at 8000 Hz, which is exactly what Twilio plays, so audio
crosses this module without a resample or a container header.

One WebSocket is held open for the whole call and utterances are multiplexed over it by
``context_id``. Opening a socket per utterance would put a TLS handshake inside the
first-audio-byte budget in docs/latency_and_cost.md.

Parameter names come from docs/vendor_params.md section 3.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

from arcagent.config import Settings
from arcagent.logging import get_logger

log = get_logger(__name__)

CARTESIA_WS_URL = "wss://api.cartesia.ai/tts/websocket"
CARTESIA_VERSION = "2024-06-10"

# The one output format this pipeline accepts. Anything else would need a resample.
OUTPUT_FORMAT = {"container": "raw", "encoding": "pcm_mulaw", "sample_rate": 8000}


@dataclass(frozen=True, slots=True)
class TtsChunk:
    """One piece of synthesised audio.

    Attributes:
        audio: raw mulaw bytes, not base64, not framed yet.
        context_id: the utterance this belongs to.
        index: position in the utterance, starting at zero.
        ts: monotonic clock reading on arrival. ``index == 0`` gives first byte latency.
    """

    audio: bytes
    context_id: str
    index: int
    ts: float


class TtsError(RuntimeError):
    """Cartesia reported an error for an utterance."""


class TtsSocket(Protocol):
    async def send(self, data: str | bytes) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def close(self) -> None: ...


Connector = Callable[[str, dict[str, str]], Awaitable[TtsSocket]]


class TtsSocketClosed(Exception):
    """The Cartesia socket went away."""


def build_socket_url() -> str:
    """The version is pinned on the query string; the key travels in a header."""
    return f"{CARTESIA_WS_URL}?{urlencode({'cartesia_version': CARTESIA_VERSION})}"


def auth_headers(settings: Settings) -> dict[str, str]:
    return {
        "X-API-Key": settings.cartesia_api_key,
        "Cartesia-Version": CARTESIA_VERSION,
    }


def build_request(
    settings: Settings,
    text: str,
    context_id: str,
    language: str = "en",
) -> dict[str, Any]:
    """The synthesis request. ``output_format`` is fixed, never taken from a caller."""
    return {
        "model_id": settings.cartesia_model_id,
        "transcript": text,
        "voice": {"mode": "id", "id": settings.cartesia_voice_id},
        "output_format": dict(OUTPUT_FORMAT),
        "language": language,
        "context_id": context_id,
        "continue": False,
    }


def build_cancel(context_id: str) -> dict[str, Any]:
    """Ask Cartesia to stop generating an utterance we are no longer going to play.

    Barge in does not depend on this landing. The caller stops reading the chunk iterator
    and sends Twilio a ``clear``; this only saves the characters we would be billed for.
    """
    return {"context_id": context_id, "cancel": True}


@dataclass(slots=True)
class _Context:
    queue: asyncio.Queue[TtsChunk | BaseException | None]
    index: int = 0
    cancelled: bool = False


class CartesiaTTS:
    """A Cartesia session for one call.

    Usage::

        async with CartesiaTTS(settings) as tts:
            async for chunk in tts.synthesize("hello"):
                ...
    """

    def __init__(
        self,
        settings: Settings,
        connect: Connector | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._connect = connect or _default_connect
        self._clock = clock
        self._socket: TtsSocket | None = None
        self._reader: asyncio.Task[None] | None = None
        self._contexts: dict[str, _Context] = {}
        self._closing = False

    async def __aenter__(self) -> CartesiaTTS:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def start(self) -> None:
        self._socket = await self._connect(build_socket_url(), auth_headers(self._settings))
        self._reader = asyncio.create_task(self._read_loop(), name="cartesia-reader")
        log.info("cartesia_connected", model_id=self._settings.cartesia_model_id)

    def new_context_id(self) -> str:
        return uuid.uuid4().hex

    async def synthesize(
        self,
        text: str,
        context_id: str | None = None,
        language: str = "en",
    ) -> AsyncIterator[TtsChunk]:
        """Stream one utterance.

        Abandoning the iterator, which is what barge in does, leaves the context registered
        until :meth:`cancel` is called, so call it in the cancellation path.

        Raises:
            TtsError: Cartesia rejected the utterance.
            TtsSocketClosed: the socket died mid utterance.
        """
        if self._socket is None:
            raise TtsSocketClosed("synthesize called before start")

        context_id = context_id or self.new_context_id()
        context = _Context(queue=asyncio.Queue())
        self._contexts[context_id] = context

        await self._socket.send(
            json.dumps(build_request(self._settings, text, context_id, language))
        )

        try:
            while True:
                item = await context.queue.get()
                if item is None:
                    return
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            self._contexts.pop(context_id, None)

    async def cancel(self, context_id: str) -> None:
        """Stop an utterance. Safe to call for a context that already finished."""
        context = self._contexts.get(context_id)
        if context is not None:
            context.cancelled = True
            context.queue.put_nowait(None)
        if self._socket is not None and not self._closing:
            try:
                await self._socket.send(json.dumps(build_cancel(context_id)))
            except Exception:
                pass

    async def _read_loop(self) -> None:
        while not self._closing:
            try:
                assert self._socket is not None
                raw = await self._socket.recv()
            except (TtsSocketClosed, ConnectionError, OSError) as exc:
                self._fail_all(exc if not self._closing else None)
                return
            except asyncio.CancelledError:
                raise
            self._dispatch(raw)

    def _dispatch(self, raw: str | bytes) -> None:
        try:
            message: dict[str, Any] = json.loads(raw)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            log.warning("cartesia_message_unparsed")
            return

        context_id = str(message.get("context_id", ""))
        context = self._contexts.get(context_id)
        if context is None or context.cancelled:
            return  # a late chunk for an utterance we abandoned

        match message.get("type"):
            case "chunk":
                data = message.get("data") or ""
                try:
                    audio = base64.b64decode(data, validate=True)
                except (base64.binascii.Error, ValueError):
                    log.warning("cartesia_chunk_undecodable", context_id=context_id)
                    return
                context.queue.put_nowait(
                    TtsChunk(
                        audio=audio,
                        context_id=context_id,
                        index=context.index,
                        ts=self._clock(),
                    )
                )
                context.index += 1
            case "done":
                context.queue.put_nowait(None)
            case "error":
                context.queue.put_nowait(TtsError(str(message.get("error", "unknown"))))
            case _:
                pass

    def _fail_all(self, exc: BaseException | None) -> None:
        for context in self._contexts.values():
            context.queue.put_nowait(exc if exc is not None else None)

    async def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._fail_all(None)
        if self._reader is not None and not self._reader.done():
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):
                pass
        if self._socket is not None:
            try:
                await self._socket.close()
            except Exception:
                pass
        log.info("cartesia_closed")


async def _default_connect(url: str, headers: dict[str, str]) -> TtsSocket:
    """Real connector. Imported lazily so tests never need the websockets client."""
    import websockets

    return await websockets.connect(url, additional_headers=headers)  # type: ignore[return-value]
