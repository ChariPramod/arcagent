"""FastAPI application: Twilio webhooks and the media stream WebSocket."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Form, Response, WebSocket
from starlette.websockets import WebSocketState

from arcagent import __version__
from arcagent.agent.graph import AgentConfig
from arcagent.agent.llm import AnthropicStructuredLLM
from arcagent.agent.responder import GraphResponder
from arcagent.config import Settings, get_settings
from arcagent.console.api import router as console_router
from arcagent.logging import configure_logging, get_logger
from arcagent.persistence.models import Outcome
from arcagent.speech.cartesia_tts import CartesiaTTS
from arcagent.speech.deepgram_stt import DeepgramSTT
from arcagent.telephony.availability import CoordinatorAvailability, get_availability
from arcagent.telephony.call_session import CallSession
from arcagent.telephony.eval_config import build_eval_config
from arcagent.telephony.persistence_sink import DatabaseTurnSink
from arcagent.telephony.routing import CallRouter
from arcagent.telephony.security import (
    validate_admin_request,
    validate_audio_eval_websocket,
    validate_twilio_request,
    validate_twilio_websocket,
)
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
app.include_router(console_router)


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


@app.get("/admin/coordinator", dependencies=[Depends(validate_admin_request)])
async def get_coordinator(settings: Settings = Depends(get_settings)) -> dict[str, bool]:
    """Whether a warm transfer would be accepted right now."""
    return {"available": get_availability(settings.coordinator_available).available}


@app.post("/admin/coordinator", dependencies=[Depends(validate_admin_request)])
async def set_coordinator(
    available: bool,
    settings: Settings = Depends(get_settings),
) -> dict[str, bool]:
    """Flip the flag. A hot lead scored above the threshold still books a callback when
    this is false, because a transfer nobody answers is worse than a booked callback."""
    flag = get_availability(settings.coordinator_available)
    return {"available": flag.set(available)}


@app.websocket("/voice/stream")
async def voice_stream(websocket: WebSocket, settings: Settings = Depends(get_settings)) -> None:
    """Twilio media stream: STT, the LangGraph agent, TTS, then routing."""
    if not await validate_twilio_websocket(websocket, settings):
        return
    await _run_voice_session(websocket, settings)


@app.websocket("/eval/voice/stream")
async def eval_voice_stream(
    websocket: WebSocket, settings: Settings = Depends(get_settings)
) -> None:
    """Explicitly enabled test-only stream; finalization never routes or sends SMS."""
    if not await validate_audio_eval_websocket(websocket, settings):
        return
    await _run_voice_session(websocket, settings, evaluation=True)


async def _run_voice_session(
    websocket: WebSocket, settings: Settings, *, evaluation: bool = False
) -> None:
    await websocket.accept()
    availability = get_availability(settings.coordinator_available)
    coordinator_available = availability.available
    if evaluation:
        try:
            snapshot = await asyncio.to_thread(build_eval_config, settings, coordinator_available)
        except Exception as exc:
            log.warning("audio_eval_config_failed", error_type=type(exc).__name__)
            await websocket.close(code=1011, reason="evaluation configuration unavailable")
            return
        await websocket.send_json({"event": "eval.config", "config": snapshot})

    stt = DeepgramSTT(settings)
    tts = CartesiaTTS(settings)
    sink = DatabaseTurnSink(settings.database_url)
    responder = GraphResponder(
        AgentConfig(
            llm=AnthropicStructuredLLM(settings),
            prompt_version=settings.prompt_version,
            threshold=settings.handoff_threshold,
            coordinator_available=coordinator_available,
        )
    )

    async def reply_complete(texts: list[str], terminal: bool) -> None:
        reply = {"texts": texts, "terminal": terminal}
        if terminal:
            reply["fields"] = responder.fields.as_lead_row()
        await websocket.send_json({"event": "eval.reply_complete", "reply": reply})

    try:
        await stt.start()
        await tts.start()
        session = CallSession(
            socket=TwilioWebSocket(websocket),
            stt=stt,
            tts=tts,
            responder=responder,
            settings=settings,
            turn_sink=sink,
            on_start=sink.open,
            on_reply_complete=reply_complete if evaluation else None,
        )
        await session.run()
        if evaluation:
            # Outcomes describe a simulation. Never execute coordinator transfers or SMS.
            outcome = (
                "language_fallback"
                if session.language_fallback
                else session.outcome or responder.outcome or "abandoned"
            )
            await sink.close(
                Outcome(outcome), final_node=f"audio_eval:{responder.node_name or 'ended'}"[:64]
            )
        else:
            await _finish_call(settings, session, responder, sink, availability)
        if websocket.client_state is WebSocketState.CONNECTED:
            await websocket.close(code=1000)
    finally:
        try:
            await stt.close()
        finally:
            await tts.close()


async def _finish_call(
    settings: Settings,
    session: CallSession,
    responder: GraphResponder,
    sink: DatabaseTurnSink,
    availability: CoordinatorAvailability,
) -> None:
    """Score, persist and route once the caller is done talking.

    A caller who was never a lead, a wrong number or an existing patient, gets no lead row
    and no score. Creating one would put a record in the CRM that a coordinator has to
    read and discard.
    """
    outcome = session.outcome or responder.outcome
    if session.language_fallback:
        await sink.close(Outcome.LANGUAGE_FALLBACK, final_node="language_fallback")
        log.info("call_ended", outcome="language_fallback", dtmf_digits=len(session.dtmf_digits))
        return

    if outcome == "abandoned" or not responder.should_end or outcome is None:
        await sink.close(Outcome.ABANDONED, final_node=responder.node_name)
        log.info("call_ended", outcome="abandoned")
        return

    if not responder.creates_a_lead or sink.call_id is None:
        await sink.close(Outcome(outcome or "abandoned"), final_node=responder.node_name)
        log.info("call_ended", outcome=outcome)
        return

    router = CallRouter(
        settings.model_copy(update={"coordinator_available": availability.available}),
        database_url=settings.database_url,
    )
    result = await router.finish_call(
        call_id=sink.call_id,
        twilio_call_sid=sink.twilio_call_sid,
        fields=responder.fields,
        consent_turn_index=sink.turn_index,
    )
    await sink.close(result.outcome, final_node=responder.node_name)
    log.info(
        "call_ended",
        outcome=str(result.outcome),
        score=result.score.score,
        decision=str(result.score.decision),
        routing_error=result.error,
    )


@app.websocket("/voice/echo")
async def voice_echo(websocket: WebSocket, settings: Settings = Depends(get_settings)) -> None:
    """Echo loop, kept for diagnosing a call where the audio itself is wrong."""
    if not settings.echo_enabled:
        await websocket.close(code=1008)
        return
    if not await validate_twilio_websocket(websocket, settings):
        return
    await websocket.accept()
    await run_echo_session(TwilioWebSocket(websocket))
