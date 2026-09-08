"""Writes a live call's turns to Postgres without blocking the audio loop.

Database work runs in a worker thread. A turn that fails to persist is logged and dropped:
losing a row is bad, stalling the audio path is worse.
"""

from __future__ import annotations

import asyncio

from arcagent.logging import get_logger
from arcagent.persistence.db import session_scope
from arcagent.persistence.models import Outcome
from arcagent.persistence.repo import CallRepository
from arcagent.telephony.call_session import TurnRecord
from arcagent.telephony.twilio_stream import StartEvent

log = get_logger(__name__)


class DatabaseTurnSink:
    """Creates the call row, appends turns, and closes the call out."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url
        self.twilio_call_sid = ""
        self.call_id: int | None = None
        self.turn_index = 0

    async def open(self, event: StartEvent) -> None:
        """Create the call row. Bound as the session's ``on_start`` hook.

        The caller's number arrives as a custom parameter on the start event, because the
        WebSocket handler never sees the original webhook request.
        """
        self.twilio_call_sid = event.call_sid
        from_number = event.custom_parameters.get("from", "")
        try:
            self.call_id = await asyncio.to_thread(self._open_sync, event.call_sid, from_number)
        except Exception:
            log.exception("call_open_failed", call_sid=event.call_sid)

    def _open_sync(self, call_sid: str, from_number: str) -> int:
        with session_scope(self.database_url) as session:
            return CallRepository(session).start_call(call_sid, from_number).id

    async def __call__(self, record: TurnRecord) -> None:
        if self.call_id is None:
            return
        index = self.turn_index
        self.turn_index += 1
        try:
            await asyncio.to_thread(self._add_turn_sync, index, record)
        except Exception:
            log.exception("turn_persist_failed", turn_index=index)

    def _add_turn_sync(self, index: int, record: TurnRecord) -> None:
        with session_scope(self.database_url) as session:
            CallRepository(session).add_turn(
                call_id=self.call_id,
                turn_index=index,
                speaker=record.speaker,
                text=record.text,
                latency=record.latency,
                interrupted=record.interrupted,
                node_name=record.node_name,
            )

    async def close(self, outcome: Outcome | str, final_node: str | None = None) -> None:
        if self.call_id is None:
            return
        try:
            await asyncio.to_thread(self._close_sync, outcome, final_node)
        except Exception:
            log.exception("call_close_failed", call_id=self.call_id)

    def _close_sync(self, outcome: Outcome | str, final_node: str | None) -> None:
        with session_scope(self.database_url) as session:
            CallRepository(session).end_call(self.call_id, outcome, final_node=final_node)
