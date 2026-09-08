"""The LangGraph qualification agent.

Implements docs/conversation_design.md. The graph owns the flow; the model owns the
phrasing. Five nodes call the model, five are pure functions, and the pure ones are
identical on every run, which is what makes the harness able to hold them to anything.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from langgraph.graph import END, StateGraph

from arcagent.agent import objections
from arcagent.agent.graph_state import AgentState, Turn, new_state
from arcagent.agent.llm import StructuredLLM
from arcagent.agent.nodes.base import record_turns, run_llm_node
from arcagent.agent.prompts import load_prompt
from arcagent.agent.schemas import (
    ContactOutput,
    InsuranceOutput,
    ObjectionOutput,
    SituationOutput,
    TreatmentInterestOutput,
)
from arcagent.agent.scoring import Decision, score
from arcagent.agent.state import LeadFields, Objection, ObjectionKind, TreatmentInterest
from arcagent.logging import get_logger

log = get_logger(__name__)

GREET = "greet_and_disclose"
TREATMENT = "confirm_treatment_interest"
SITUATION = "assess_situation"
INSURANCE = "extract_insurance_signal"
OBJECTION = "handle_objection"
CONTACT = "capture_contact"
ROUTE = "score_and_route"
TRANSFER = "warm_transfer"
CALLBACK = "book_callback_and_sms"
END_CALL = "end_call"

# The happy path. An objection diverts out of it and returns to the same place.
QUALIFY_SEQUENCE = (TREATMENT, SITUATION, INSURANCE, CONTACT)

LLM_NODES: dict[str, type] = {
    TREATMENT: TreatmentInterestOutput,
    SITUATION: SituationOutput,
    INSURANCE: InsuranceOutput,
    CONTACT: ContactOutput,
    OBJECTION: ObjectionOutput,
}


class AgentConfig:
    """Everything the graph needs that is not conversation state."""

    def __init__(
        self,
        llm: StructuredLLM,
        prompt_version: str = "v1",
        threshold: int = 60,
        coordinator_available: bool = True,
        model: str | None = None,
    ) -> None:
        self.llm = llm
        self.prompt_version = prompt_version
        self.threshold = threshold
        self.coordinator_available = coordinator_available
        self.model = model


# ------------------------------------------------------------------ pure nodes


def greet_and_disclose(state: AgentState, config: AgentConfig) -> dict[str, Any]:
    """Speak the disclosure verbatim. No model call, so it is identical on every call.

    Only the last paragraph of the prompt file is spoken; the rest is notes for the owner.
    Line wrapping is collapsed, because the text goes to a speech synthesiser that would
    otherwise be handed a hard wrapped paragraph.
    """
    greeting = load_prompt("greeting", config.prompt_version)
    spoken = " ".join(greeting.split("\n\n")[-1].split())
    return {
        "pending_utterances": [spoken],
        "history": [Turn(speaker="agent", text=spoken, node=GREET)],
        "current_node": TREATMENT,
    }


def score_and_route(state: AgentState, config: AgentConfig) -> dict[str, Any]:
    """Pure. Reads the accumulated fields, calls scoring.py, chooses the route."""
    result = score(
        state["fields"],
        threshold=config.threshold,
        coordinator_available=config.coordinator_available,
    )
    log.info(
        "lead_scored",
        score=result.score,
        decision=str(result.decision),
        threshold=result.threshold_used,
    )
    return {
        "score": result.score,
        "score_breakdown": result.breakdown,
        "decision": str(result.decision),
        "current_node": TRANSFER if result.is_handoff else CALLBACK,
    }


def warm_transfer(state: AgentState, config: AgentConfig) -> dict[str, Any]:
    """Announce the handoff. The Twilio side effect is the audio loop's job, not the graph's."""
    line = "Great, I am connecting you with a treatment coordinator now. One moment."
    return {
        "pending_utterances": [line],
        "history": [Turn(speaker="agent", text=line, node=TRANSFER)],
        "outcome": "handoff",
        "current_node": END_CALL,
    }


def book_callback_and_sms(state: AgentState, config: AgentConfig) -> dict[str, Any]:
    """Announce the callback. Slot selection and the SMS are the audio loop's job."""
    line = "I will have a coordinator call you back, and I will text you the time."
    return {
        "pending_utterances": [line],
        "history": [Turn(speaker="agent", text=line, node=CALLBACK)],
        "outcome": "callback_booked",
        "current_node": END_CALL,
    }


def end_call(state: AgentState, config: AgentConfig) -> dict[str, Any]:
    return {
        "finished": True,
        "outcome": state.get("outcome") or "abandoned",
        "current_node": END_CALL,
    }


# ------------------------------------------------------------------- llm nodes


def _make_llm_node(node_name: str):
    """Build the graph callable for one model backed node."""
    schema = LLM_NODES[node_name]

    async def node(state: AgentState, config: AgentConfig) -> dict[str, Any]:
        result, fields = await run_llm_node(
            state, node_name, schema, config.llm, config.prompt_version, config.model
        )
        spoken = result.parsed.next_utterance
        update: dict[str, Any] = {
            "fields": fields,
            "pending_utterances": [spoken],
            "history": record_turns(node_name, state.get("caller_utterance", ""), spoken),
            "llm_ttft_s": result.ttft_s,
            "caller_utterance": "",
        }
        if node_name == OBJECTION:
            update |= _close_objection(state, result.parsed)
        else:
            update["current_node"] = _advance(node_name, fields)
            if fields.treatment_interest is TreatmentInterest.WRONG_NUMBER:
                update["outcome"] = "wrong_number"
        return update

    node.__name__ = node_name
    return node


def _advance(node_name: str, fields: LeadFields) -> str:
    """Where the happy path goes after this node."""
    if node_name == TREATMENT and fields.treatment_interest is TreatmentInterest.WRONG_NUMBER:
        return END_CALL
    index = QUALIFY_SEQUENCE.index(node_name)
    if index + 1 < len(QUALIFY_SEQUENCE):
        return QUALIFY_SEQUENCE[index + 1]
    return ROUTE


def _close_objection(state: AgentState, output: ObjectionOutput) -> dict[str, Any]:
    """Record how the objection ended and go back to where the conversation was."""
    kind = state.get("open_objection")
    fields = state["fields"]
    if kind is not None:
        objection = Objection(
            kind=ObjectionKind(kind),
            recovered=output.recovered,
            turn_index=len(state.get("history", [])),
        )
        fields = dataclasses.replace(fields, objections=[*fields.objections, objection])
    return {
        "fields": fields,
        "open_objection": None if output.recovered else kind,
        "current_node": state.get("return_to") or ROUTE,
        "return_to": None,
    }


# ------------------------------------------------------------------ objections


def detect_objection(state: AgentState, config: AgentConfig) -> dict[str, Any]:
    """Runs after every caller turn. Can divert any node into ``handle_objection``."""
    text = state.get("caller_utterance", "")
    detected = objections.detect_keywords(text)
    already_open = state.get("open_objection") is not None
    if not objections.should_enter_handler(detected, already_open):
        return {}
    log.info("objection_detected", kind=str(detected))
    return {
        "open_objection": str(detected),
        "return_to": state.get("current_node"),
        "current_node": OBJECTION,
    }


# ----------------------------------------------------------------- graph build


def build_graph(config: AgentConfig):
    """Compile the graph. One node per file's worth of responsibility, wired by state."""
    builder: StateGraph = StateGraph(AgentState)

    def bind(fn):
        async def wrapped(state: AgentState) -> dict[str, Any]:
            result = fn(state, config)
            return await result if hasattr(result, "__await__") else result

        wrapped.__name__ = fn.__name__
        return wrapped

    builder.add_node(GREET, bind(greet_and_disclose))
    for name in LLM_NODES:
        builder.add_node(name, bind(_make_llm_node(name)))
    builder.add_node(ROUTE, bind(score_and_route))
    builder.add_node(TRANSFER, bind(warm_transfer))
    builder.add_node(CALLBACK, bind(book_callback_and_sms))
    builder.add_node(END_CALL, bind(end_call))

    builder.set_entry_point(GREET)
    builder.add_edge(GREET, END)
    for name in LLM_NODES:
        builder.add_edge(name, END)
    builder.add_edge(ROUTE, END)
    builder.add_edge(TRANSFER, END)
    builder.add_edge(CALLBACK, END)
    builder.add_edge(END_CALL, END)

    return builder.compile()


NODE_FUNCTIONS = {
    GREET: greet_and_disclose,
    ROUTE: score_and_route,
    TRANSFER: warm_transfer,
    CALLBACK: book_callback_and_sms,
    END_CALL: end_call,
}


class Conversation:
    """Drives the graph one caller turn at a time.

    LangGraph runs one node per invocation here rather than a single sweep, because the
    conversation is inherently turn based: a node runs, the agent speaks, and the graph
    must stop and wait for a human before the next node can run. Nodes that speak nothing
    and need no caller input (scoring, routing, ending) are chained without waiting.
    """

    # Nodes that run without anything from the caller. Reaching one of these means the
    # turn keeps going: scoring, routing and ending all happen in the same breath as the
    # node that led to them, not after another caller utterance.
    NEEDS_NO_INPUT = frozenset({ROUTE, TRANSFER, CALLBACK, END_CALL})

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.graph = build_graph(config)
        self.state: AgentState = new_state()

    async def start(self) -> list[str]:
        """Run the greeting. Returns what the agent says."""
        return await self._run_until_caller_needed()

    async def say(self, caller_text: str) -> list[str]:
        """Feed one caller utterance and run until the agent needs the caller again."""
        if self.state.get("finished"):
            return []
        self.state["caller_utterance"] = caller_text
        self._apply(detect_objection(self.state, self.config))
        return await self._run_until_caller_needed()

    async def _run_until_caller_needed(self) -> list[str]:
        spoken: list[str] = []
        for _ in range(8):  # a turn never legitimately chains more than a few nodes
            node = self.state.get("current_node", END_CALL)
            before = len(self.state.get("pending_utterances", []))
            update = await self.graph.nodes[node].ainvoke(self.state)  # type: ignore[union-attr]
            self._apply(update)
            spoken.extend(self.state.get("pending_utterances", [])[before:])
            if self.state.get("finished"):
                break
            if self.state.get("current_node") not in self.NEEDS_NO_INPUT:
                break
        return spoken

    def _apply(self, update: dict[str, Any]) -> None:
        for key, value in update.items():
            if key in ("history", "pending_utterances"):
                self.state[key] = [*self.state.get(key, []), *value]  # type: ignore[literal-required]
            else:
                self.state[key] = value  # type: ignore[literal-required]

    @property
    def fields(self) -> LeadFields:
        return self.state["fields"]

    @property
    def finished(self) -> bool:
        return bool(self.state.get("finished"))

    @property
    def outcome(self) -> str | None:
        return self.state.get("outcome")

    @property
    def decision(self) -> Decision | None:
        raw = self.state.get("decision")
        return Decision(raw) if raw else None
