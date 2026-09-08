"""Whether a coordinator is there to take a warm transfer.

Process local on purpose. This is a demo flag flipped from a phone before a test call, not
a rota system. A real deployment reads this from whatever the practice already uses, and
this module is the seam where that swap happens.
"""

from __future__ import annotations

from dataclasses import dataclass

from arcagent.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class CoordinatorAvailability:
    """A single flag, readable and settable."""

    available: bool = True

    def set(self, available: bool) -> bool:
        if available != self.available:
            log.info("coordinator_availability_changed", available=available)
        self.available = available
        return self.available


_state: CoordinatorAvailability | None = None


def get_availability(default: bool = True) -> CoordinatorAvailability:
    """The process wide flag, seeded from settings on first use."""
    global _state
    if _state is None:
        _state = CoordinatorAvailability(available=default)
    return _state


def reset_availability() -> None:
    """Test hook."""
    global _state
    _state = None
