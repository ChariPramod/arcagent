"""FastAPI application: Twilio webhooks and the media stream WebSocket."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Response, WebSocket

from arcagent import __version__
from arcagent.config import Settings, get_settings
from arcagent.logging import configure_logging, get_logger
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
async def voice_inbound(settings: Settings = Depends(get_settings)) -> Response:
    """Twilio voice webhook. Answers by connecting a bidirectional media stream."""
    twiml = connect_stream(settings.stream_url)
    log.info("inbound_call_answered", stream_url=settings.stream_url)
    return Response(content=twiml, media_type="application/xml")


@app.websocket("/voice/stream")
async def voice_stream(websocket: WebSocket) -> None:
    """Twilio media stream. Currently an echo loop, replaced by the agent in T9."""
    await websocket.accept()
    await run_echo_session(TwilioWebSocket(websocket))
