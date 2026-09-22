"""End of call: persist the lead, score it, and take the routing action.

One place, so the order is visible: score before route, persist before act, and never act
on a decision that was not written down first. If the transfer fails after the lead is
saved, the lead is still there and a human can pick it up. The reverse would lose it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from arcagent.agent.scoring import Decision, ScoreResult, score
from arcagent.agent.state import LeadFields
from arcagent.config import Settings
from arcagent.logging import get_logger
from arcagent.persistence.db import session_scope
from arcagent.persistence.models import Call, Outcome
from arcagent.persistence.repo import CallRepository
from arcagent.telephony.transfer_state import TransferStateError, begin_transfer, mark_request
from arcagent.telephony.twilio_actions import (
    SmsFailed,
    TransferFailed,
    TwilioActions,
)

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RoutingResult:
    """What happened at the end of the call."""

    score: ScoreResult
    outcome: Outcome | None
    lead_id: int | None = None
    slot_start: datetime | None = None
    sms_sid: str | None = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


class CallRouter:
    """Scores a finished conversation and carries out the decision."""

    def __init__(
        self,
        settings: Settings,
        actions: TwilioActions | None = None,
        database_url: str | None = None,
    ) -> None:
        self.settings = settings
        self.actions = actions or TwilioActions(settings)
        self.database_url = database_url

    async def finish_call(
        self,
        call_id: int,
        twilio_call_sid: str,
        fields: LeadFields,
        consent_turn_index: int | None = None,
    ) -> RoutingResult:
        """Score, persist, route; report database and vendor failures to the caller."""
        result = score(
            fields,
            threshold=self.settings.handoff_threshold,
            coordinator_available=self.settings.coordinator_available,
        )
        try:
            lead_id, slot_start = await asyncio.to_thread(
                self._persist, call_id, fields, result, consent_turn_index
            )
        except SQLAlchemyError:
            # Database exceptions may contain query parameters with caller data.
            log.error("routing_persistence_failed", call_id=call_id)
            return RoutingResult(
                score=result, outcome=Outcome.ABANDONED, error="routing persistence failed"
            )

        if result.decision is Decision.HANDOFF:
            return await self._transfer(call_id, twilio_call_sid, result, lead_id)
        return await self._callback(call_id, lead_id, fields, result, slot_start)

    # ------------------------------------------------------------- persistence

    def _persist(
        self,
        call_id: int,
        fields: LeadFields,
        result: ScoreResult,
        consent_turn_index: int | None,
    ) -> tuple[int | None, datetime | None]:
        """Write the lead, the score, and, for a callback, hold a slot. Runs in a thread."""
        with session_scope(self.database_url) as session:
            repo = CallRepository(session)
            lead = repo.save_lead(call_id, fields.as_lead_row())
            repo.save_score(
                lead.id,
                result.score,
                result.threshold_used,
                result.decision.value,
                result.breakdown,
            )
            if result.decision is Decision.HANDOFF or not fields.callback_number:
                return lead.id, None

            slot = repo.next_open_slot()
            if slot is None:
                log.warning("no_open_callback_slot", lead_id=lead.id)
                return lead.id, None
            repo.book_callback(lead.id, slot, consent_turn_index=consent_turn_index)
            return lead.id, slot.slot_start

    def _record_sms(self, lead_id: int, sms_sid: str, sms_status: str) -> None:
        from sqlalchemy import select

        from arcagent.persistence.models import Callback

        with session_scope(self.database_url) as session:
            callback = session.scalar(
                select(Callback)
                .where(Callback.lead_id == lead_id)
                .order_by(Callback.id.desc())
                .limit(1)
            )
            if callback is not None:
                CallRepository(session).record_sms(callback.id, sms_sid, sms_status)

    # ----------------------------------------------------------------- actions

    def _begin_transfer(self, call_id: int, twilio_call_sid: str) -> tuple[str, bool]:
        with session_scope(self.database_url) as session:
            call = session.get(Call, call_id)
            if call is None or call.twilio_call_sid != twilio_call_sid:
                raise TransferStateError("Transfer identity mismatch")
            attempt, created = begin_transfer(session, call_id)
            return attempt.id, created

    def _mark_transfer(self, identifier: str, disposition: str) -> Outcome | None:
        with session_scope(self.database_url) as session:
            attempt = mark_request(session, identifier, disposition)
            return session.get(Call, attempt.call_id).outcome

    async def _transfer(
        self, call_id: int, twilio_call_sid: str, result: ScoreResult, lead_id: int | None
    ) -> RoutingResult:
        try:
            identifier, created = await asyncio.to_thread(
                self._begin_transfer, call_id, twilio_call_sid
            )
        except (SQLAlchemyError, TransferStateError):
            return RoutingResult(
                score=result,
                outcome=None,
                lead_id=lead_id,
                error="Transfer intent could not be persisted",
            )
        if not created:
            return RoutingResult(
                score=result,
                outcome=None,
                lead_id=lead_id,
                error="Transfer already requested; awaiting reconciliation",
            )
        error = None
        disposition = "accepted"
        try:
            await asyncio.to_thread(
                self.actions.warm_transfer, twilio_call_sid, attempt_id=identifier
            )
        except TransferFailed as exc:
            disposition = "uncertain" if exc.uncertain else "failed"
            error = str(exc)
        try:
            outcome = await asyncio.to_thread(self._mark_transfer, identifier, disposition)
        except SQLAlchemyError:
            # Intent remains durable. Never repeat a possibly accepted vendor update.
            return RoutingResult(
                score=result,
                outcome=None,
                lead_id=lead_id,
                error="Transfer requested but receipt persistence failed",
            )
        return RoutingResult(score=result, outcome=outcome, lead_id=lead_id, error=error)

    async def _callback(
        self,
        call_id: int,
        lead_id: int | None,
        fields: LeadFields,
        result: ScoreResult,
        slot_start: datetime | None,
    ) -> RoutingResult:
        if not fields.callback_number:
            return RoutingResult(
                score=result,
                outcome=Outcome.ABANDONED,
                lead_id=lead_id,
                error="no callback number captured",
            )
        if slot_start is None:
            return RoutingResult(
                score=result,
                outcome=Outcome.ABANDONED,
                lead_id=lead_id,
                error="no open slot",
            )

        try:
            receipt = await asyncio.to_thread(
                self.actions.send_callback_sms, fields.callback_number, slot_start
            )
        except SmsFailed as exc:
            return RoutingResult(
                score=result,
                outcome=Outcome.CALLBACK_BOOKED,
                lead_id=lead_id,
                slot_start=slot_start,
                error=str(exc),
            )

        if lead_id is not None:
            try:
                await asyncio.to_thread(self._record_sms, lead_id, receipt.sid, receipt.status)
            except SQLAlchemyError:
                log.error("sms_receipt_persistence_failed", call_id=call_id, lead_id=lead_id)
                return RoutingResult(
                    score=result,
                    outcome=Outcome.CALLBACK_BOOKED,
                    lead_id=lead_id,
                    slot_start=slot_start,
                    sms_sid=receipt.sid,
                    error="SMS sent but receipt persistence failed",
                )
        return RoutingResult(
            score=result,
            outcome=Outcome.CALLBACK_BOOKED,
            lead_id=lead_id,
            slot_start=slot_start,
            sms_sid=receipt.sid,
        )
