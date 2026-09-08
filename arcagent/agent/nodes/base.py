"""Shared node machinery.

The rule that matters here: a null in a node's structured output never overwrites a value
already in state. A caller who answered the insurance question two turns ago does not have
that answer erased because the model returned null this turn.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Any

from arcagent.agent.graph_state import AgentState, Turn
from arcagent.agent.llm import LLMResult, StructuredLLM
from arcagent.agent.prompts import load_prompt
from arcagent.agent.schemas import NodeOutput
from arcagent.agent.state import LeadFields
from arcagent.logging import get_logger

log = get_logger(__name__)

# Fields a node may set on LeadFields through its structured output. Anything else the
# model returns is ignored rather than written, so a schema change cannot silently start
# writing a column nobody reviewed.
ASSIGNABLE_FIELDS = frozenset(
    {
        "treatment_interest",
        "missing_teeth_count",
        "pain_level",
        "considering_duration",
        "has_insurance",
        "employer_name",
        "plan_type",
        "coverage_awareness",
        "financing_asked",
        "callback_declined",
        "name",
        "callback_number",
        "preferred_time",
    }
)


def build_messages(state: AgentState) -> list[dict[str, Any]]:
    """The conversation so far, in Messages API shape.

    The caller always speaks last, because a node runs in response to a caller turn.
    """
    messages: list[dict[str, Any]] = []
    for turn in state.get("history", []):
        role = "user" if turn["speaker"] == "caller" else "assistant"
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += f"\n{turn['text']}"
        else:
            messages.append({"role": role, "content": turn["text"]})
    if not messages or messages[0]["role"] != "user":
        messages.insert(0, {"role": "user", "content": "(the caller has just been greeted)"})
    return messages


def system_prompt(node_name: str, version: str) -> str:
    """The shared system prompt plus this node's own."""
    return f"{load_prompt('system', version)}\n\n{load_prompt(node_name, version)}"


def apply_output(fields: LeadFields, output: NodeOutput) -> LeadFields:
    """Fold a node's structured output into the accumulated fields.

    A null is "the caller has not told us", not "the answer is nothing", so nulls are
    skipped. Booleans that default to False are skipped when False for the same reason:
    ``callback_declined=False`` from a node that never asked must not clear a decline the
    caller already made.
    """
    updates: dict[str, Any] = {}
    for key, value in output.model_dump(exclude={"next_utterance"}).items():
        if key not in ASSIGNABLE_FIELDS or value is None:
            continue
        if isinstance(value, bool) and value is False:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        updates[key] = value
    return dataclasses.replace(fields, **updates) if updates else fields


def record_turns(
    node_name: str,
    caller_text: str,
    agent_text: str,
) -> list[Turn]:
    """History entries for one exchange."""
    turns: list[Turn] = []
    if caller_text:
        turns.append(Turn(speaker="caller", text=caller_text, node=node_name))
    if agent_text:
        turns.append(Turn(speaker="agent", text=agent_text, node=node_name))
    return turns


async def run_llm_node(
    state: AgentState,
    node_name: str,
    schema: type[NodeOutput],
    llm: StructuredLLM,
    prompt_version: str,
    model: str | None = None,
) -> tuple[LLMResult, LeadFields]:
    """Call the model for one node and fold the result into the fields."""
    result = await llm.complete(
        system=system_prompt(node_name, prompt_version),
        messages=build_messages(state),
        schema=schema,
        model=model,
    )
    return result, apply_output(state["fields"], result.parsed)


def next_of(sequence: Sequence[str], current: str, default: str) -> str:
    """The node after ``current`` in the happy path order."""
    try:
        return sequence[sequence.index(current) + 1]
    except (ValueError, IndexError):
        return default
