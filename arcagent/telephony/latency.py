"""Per turn latency accounting.

Every turn records the four stages in the budget table in docs/latency_and_cost.md:

    stt_final_ms       last inbound audio frame to receipt of the turn boundary
    llm_ttft_ms        agent invocation to its first yielded response chunk
    tts_first_byte_ms  synthesis requested to Cartesia's first audio byte
    playback_start_ms  first frame written to Twilio to playback completion acknowledgement

The legacy column names are retained for compatibility. Inbound frames include silence,
so stt_final_ms is not end-of-speech latency. A structured responder may yield only after
its entire LLM request completes, so llm_ttft_ms is not necessarily provider token TTFT.
Twilio marks acknowledge completed playback, not the first audio heard by the caller.

All four are milliseconds against a monotonic clock. A stage that did not happen stays
None, which is different from zero, and the database column is nullable for that reason.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field


def _ms(start: float | None, end: float | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, round((end - start) * 1000))


@dataclass(slots=True)
class TurnTimings:
    """Mutable stopwatch for one turn. Marked as the turn progresses, read once at the end."""

    clock: Callable[[], float] = field(default=time.monotonic, repr=False)

    last_audio_frame_at: float | None = None
    stt_final_at: float | None = None
    llm_started_at: float | None = None
    llm_first_token_at: float | None = None
    tts_requested_at: float | None = None
    tts_first_byte_at: float | None = None
    first_frame_written_at: float | None = None
    playback_started_at: float | None = None

    def mark_audio_frame(self) -> None:
        """Called for every inbound frame. The last one before a final anchors stt_final_ms."""
        self.last_audio_frame_at = self.clock()

    def mark_stt_final(self, at: float | None = None) -> None:
        self.stt_final_at = at if at is not None else self.clock()

    def mark_llm_start(self) -> None:
        self.llm_started_at = self.clock()

    def mark_llm_first_token(self) -> None:
        if self.llm_first_token_at is None:
            self.llm_first_token_at = self.clock()

    def mark_tts_request(self) -> None:
        self.tts_requested_at = self.clock()

    def mark_tts_first_byte(self, at: float | None = None) -> None:
        if self.tts_first_byte_at is None:
            self.tts_first_byte_at = at if at is not None else self.clock()

    def mark_first_frame_written(self) -> None:
        if self.first_frame_written_at is None:
            self.first_frame_written_at = self.clock()

    def mark_playback_started(self) -> None:
        if self.playback_started_at is None:
            self.playback_started_at = self.clock()

    @property
    def stt_final_ms(self) -> int | None:
        return _ms(self.last_audio_frame_at, self.stt_final_at)

    @property
    def llm_ttft_ms(self) -> int | None:
        return _ms(self.llm_started_at, self.llm_first_token_at)

    @property
    def tts_first_byte_ms(self) -> int | None:
        return _ms(self.tts_requested_at, self.tts_first_byte_at)

    @property
    def playback_start_ms(self) -> int | None:
        return _ms(self.first_frame_written_at, self.playback_started_at)

    @property
    def response_ms(self) -> int | None:
        """Boundary receipt to first agent audio written; not caller-perceived latency."""
        return _ms(self.stt_final_at, self.first_frame_written_at)

    def as_columns(self) -> dict[str, int | None]:
        """The four stage columns, ready to write to the ``turns`` row."""
        return {
            "stt_final_ms": self.stt_final_ms,
            "llm_ttft_ms": self.llm_ttft_ms,
            "tts_first_byte_ms": self.tts_first_byte_ms,
            "playback_start_ms": self.playback_start_ms,
        }
