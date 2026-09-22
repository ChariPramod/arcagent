"""Signed transfer evidence and deterministic recovery, with no external side effects."""

import asyncio
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from arcagent.config import Settings, get_settings
from arcagent.persistence.db import session_scope
from arcagent.telephony.security import validate_twilio_request
from arcagent.telephony.transfer_state import TransferStateError, record_outcome, record_progress
from arcagent.telephony.twiml import say_and_hangup


async def _require_signature(request: Request, settings: Settings = Depends(get_settings)) -> None:
    # These callbacks mutate persisted outcomes even in development. Never admit
    # unsigned evidence through the local inbound-webhook convenience switch.
    await validate_twilio_request(
        request, settings.model_copy(update={"validate_twilio_signature": True})
    )


router = APIRouter(prefix="/voice/transfer", dependencies=[Depends(_require_signature)])
RECOVERY_MESSAGE = (
    "We could not complete the connection. Please contact the office directly. Goodbye."
)


async def _fields(request: Request, settings: Settings) -> dict[str, str]:
    form = await request.form()
    if any(len(form.getlist(key)) != 1 for key in form):
        raise HTTPException(400, "Duplicate callback fields")
    data = {key: str(value) for key, value in form.items()}
    if not settings.twilio_account_sid or not secrets.compare_digest(
        data.get("AccountSid", "").encode(), settings.twilio_account_sid.encode()
    ):
        raise HTTPException(403, "Invalid callback account")
    return data


def _apply(identifier: UUID, data: dict[str, str], settings: Settings, *, progress: bool) -> str:
    with session_scope(settings.database_url) as session:
        if progress:
            sequence = data.get("SequenceNumber", "")
            if (
                not sequence.isascii()
                or not sequence.isdecimal()
                or len(sequence) > 10
                or int(sequence) > 2147483647
            ):
                raise TransferStateError("Invalid progress sequence")
            record_progress(
                session,
                str(identifier),
                parent_call_sid=data.get("ParentCallSid", ""),
                child_call_sid=data.get("CallSid", ""),
                sequence=int(sequence),
                status=data.get("CallStatus", ""),
            )
            return ""
        status = data.get("DialCallStatus", "")
        bridged = data.get("DialBridged", "")
        if status not in {"completed", "busy", "no-answer", "failed", "canceled"}:
            raise TransferStateError("Unsupported dial result")
        if bridged not in {"true", "false"}:
            raise TransferStateError("Missing bridge evidence")
        if status != "completed" and bridged == "true":
            raise TransferStateError("Conflicting bridge evidence")
        outcome = status.replace("-", "_")
        if status == "completed" and bridged == "false":
            outcome = "unbridged"
        attempt = record_outcome(
            session,
            str(identifier),
            parent_call_sid=data.get("CallSid", ""),
            child_call_sid=data.get("DialCallSid", ""),
            outcome=outcome,
            connection_confirmed=bridged == "true",
        )
        # Use stored terminal decision on retries, even conflicting late evidence.
        if attempt.outcome == "completed":
            return '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup /></Response>'
        return say_and_hangup(RECOVERY_MESSAGE)


async def _handle(
    identifier: UUID, request: Request, settings: Settings, *, progress: bool
) -> Response:
    data = await _fields(request, settings)
    try:
        twiml = await asyncio.to_thread(_apply, identifier, data, settings, progress=progress)
    except TransferStateError:
        raise HTTPException(400, "Invalid transfer evidence") from None
    except SQLAlchemyError:
        raise HTTPException(503, "Transfer evidence could not be persisted") from None
    return Response(status_code=204) if progress else Response(twiml, media_type="application/xml")


@router.post("/{identifier}/progress")
async def transfer_progress(
    identifier: UUID, request: Request, settings: Settings = Depends(get_settings)
) -> Response:
    return await _handle(identifier, request, settings, progress=True)


@router.post("/{identifier}/action")
async def transfer_action(
    identifier: UUID, request: Request, settings: Settings = Depends(get_settings)
) -> Response:
    return await _handle(identifier, request, settings, progress=False)
