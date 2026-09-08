"""FastAPI application: Twilio webhooks and the media stream WebSocket."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Form, Response, WebSocket

from arcagent import __version__
from arcagent.config import Settings, get_settings
from arcagent.logging import configure_logging, get_logger
from arcagent.persistence.models import Outcome
from arcagent.speech.cartesia_tts import CartesiaTTS
from arcagent.speech.deepgram_stt import DeepgramSTT
from arcagent.telephony.call_session import CallSession, ParrotResponder
from arcagent.telephony.persistence_sink import DatabaseTurnSink
from arcagent.telephony.security import validate_twilio_request
from arcagent.telephony.session_handler import TwilioWebSocket, run_echo_session
from arcagent.telephony.twiml import connect_stream

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.env == "prod")
    log.info("startup", env=settings.env, version=__version__)
    yield
    log.info("shutdown")


app = FastAPI(title="ArcAgent", version=__version__, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe. Reports nothing about configuration or credentials."""
    return {"status": "ok", "version": __version__}


@app.post("/voice/inbound", dependencies=[Depends(validate_twilio_request)])
async def voice_inbound(
    settings: Settings = Depends(get_settings),
    CallSid: str = Form(default=""),
    From: str = Form(default=""),
) -> Response:
    """Twilio voice webhook. Answers by connecting a bidirectional media stream.

    The call sid and the caller's number are passed as stream parameters, because the
    WebSocket handler is a separate connection that never sees this request.
    """
    twiml = connect_stream(settings.stream_url, {"call_sid": CallSid, "from": From})
    log.info("inbound_call_answered", stream_url=settings.stream_url, call_sid=CallSid)
    return Response(content=twiml, media_type="application/xml")


@app.websocket("/voice/stream")
async def voice_stream(websocket: WebSocket) -> None:
    """Twilio media stream: STT, agent, TTS.

    The responder is the parrot until the LangGraph agent lands in T9.
    """
    await websocket.accept()
    settings = get_settings()
    socket = TwilioWebSocket(websocket)

    stt = DeepgramSTT(settings)
    tts = CartesiaTTS(settings)
    sink = DatabaseTurnSink()

    await stt.start()
    await tts.start()
    session = CallSession(
        socket=socket,
        stt=stt,
        tts=tts,
        responder=ParrotResponder(),
        settings=settings,
        turn_sink=sink,
        on_start=sink.open,
    )
    try:
        await session.run()
    finally:
        await sink.close(Outcome.ABANDONED, final_node=session.responder.node_name)
        await stt.close()
        await tts.close()


@app.websocket("/voice/echo")
async def voice_echo(websocket: WebSocket) -> None:
    """Echo loop, kept for diagnosing a call where the audio itself is wrong."""
    await websocket.accept()
    await run_echo_session(TwilioWebSocket(websocket))
