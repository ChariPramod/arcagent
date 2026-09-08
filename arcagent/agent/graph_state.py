"""The LangGraph state.

Separate from ``LeadFields`` on purpose. ``LeadFields`` is the scorer's input and stays a
plain dataclass with no graph concepts in it, so scoring can be tested with nothing else
imported. This is everything else the conversation needs to carry.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from arcagent.agent.state import LeadFields


def _replace(_old: Any, new: Any) -> Any:
    """Last write wins. The default for scalar channels."""
    return new


def _append(old: list, new: list) -> list:
    return [*old, *new]


class Turn(TypedDict):
    speaker: str
    text: str
    node: str | None


class AgentState(TypedDict, total=False):
    """Channels the graph reads and writes.

    ``fields`` is the accumulated extraction. ``current_node`` is where the conversation
    is. ``return_to`` is where objection handling goes back to, which is what stops an
    objection from losing the caller's place.
    """

    caller_utterance: str
    history: Annotated[list[Turn], _append]
    fields: Annotated[LeadFields, _replace]

    current_node: Annotated[str, _replace]
    return_to: Annotated[str | None, _replace]
    open_objection: Annotated[str | None, _replace]

    pending_utterances: Annotated[list[str], _append]
    finished: Annotated[bool, _replace]
    outcome: Annotated[str | None, _replace]
    decision: Annotated[str | None, _replace]
    score: Annotated[int | None, _replace]
    score_breakdown: Annotated[dict[str, int] | None, _replace]

    # Latency, in seconds, of the model call this turn. Converted to the ms column by the
    # audio loop; kept here so the text harness can report it too.
    llm_ttft_s: Annotated[float | None, _replace]


def new_state() -> AgentState:
    """A fresh conversation."""
    return AgentState(
        caller_utterance="",
        history=[],
        fields=LeadFields(),
        current_node="greet_and_disclose",
        return_to=None,
        open_objection=None,
        pending_utterances=[],
        finished=False,
        outcome=None,
        decision=None,
        score=None,
        score_breakdown=None,
        llm_ttft_s=None,
    )
