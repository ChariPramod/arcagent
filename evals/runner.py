"""Tier 1: drive the LangGraph agent from a persona, in text, and score the result.

No audio, no telephony, no cost beyond the two model calls per turn. This tier cannot see
STT errors, endpointing, or barge in; that is what tier 2 is for, and the README says so.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from arcagent.agent.graph import AgentConfig
from arcagent.agent.llm import LLMError, StructuredLLM
from arcagent.agent.responder import GraphResponder
from arcagent.logging import get_logger
from evals import metrics
from evals.persona import Persona
from evals.simulator import SimulatedCaller

log = get_logger(__name__)


def git_sha() -> str:
    """The commit a run is tagged with. Unknown is recorded, never faked."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


@dataclass
class ScenarioResult:
    """One persona, run once."""

    scenario_id: str
    group: str
    repeat_index: int
    expected: dict[str, Any]
    actual: dict[str, Any]
    passed: bool
    field_accuracy: float
    handoff_expected: bool
    handoff_actual: bool
    fallback_activated: bool
    outcome_expected: str
    outcome_actual: str | None
    handle_time_s: float
    turns: int
    crm_completeness: float
    missed_fields: tuple[str, ...] = ()
    transcript: list[tuple[str, str]] = field(default_factory=list)
    error: str | None = None

    @property
    def outcome_correct(self) -> bool:
        return metrics.outcome_correct(self.outcome_expected, self.outcome_actual)


async def run_scenario(
    persona: Persona,
    agent_llm: StructuredLLM,
    caller_llm: StructuredLLM,
    prompt_version: str = "v1",
    threshold: int = 60,
    coordinator_available: bool = True,
    repeat_index: int = 0,
    caller_model: str | None = None,
) -> ScenarioResult:
    """Play one persona against the agent and score what happened."""
    started = time.monotonic()
    responder = GraphResponder(
        AgentConfig(
            llm=agent_llm,
            prompt_version=prompt_version,
            threshold=threshold,
            coordinator_available=coordinator_available,
        )
    )
    caller = SimulatedCaller(persona=persona, llm=caller_llm, model=caller_model)
    error: str | None = None

    try:
        agent_lines = [line async for line in responder.greet()]
        while not responder.should_end and not caller.exhausted:
            turn = await caller.reply_to(agent_lines)
            if turn.hung_up or not turn.utterance.strip():
                break
            agent_lines = [line async for line in responder.respond(turn.utterance)]
    except LLMError as exc:
        error = str(exc)
        log.warning("scenario_failed", scenario_id=persona.id, error=error)

    for line in agent_lines if not error else []:
        caller.transcript.append(("agent", line))

    return _score(persona, responder, caller, repeat_index, time.monotonic() - started, error)


def _score(
    persona: Persona,
    responder: GraphResponder,
    caller: SimulatedCaller,
    repeat_index: int,
    elapsed: float,
    error: str | None,
) -> ScenarioResult:
    actual_fields = responder.fields.as_lead_row()
    accuracy = metrics.field_accuracy(
        persona.expected.fields, actual_fields, persona.expected.not_expected
    )
    outcome_actual = responder.outcome
    handoff_actual = outcome_actual == "handoff"
    fallback_activated = bool(responder.fields.objections)

    passed = (
        error is None
        and metrics.outcome_correct(persona.expected.outcome, outcome_actual)
        and handoff_actual == persona.expected.handoff
        and not accuracy.missed
    )

    return ScenarioResult(
        scenario_id=persona.id,
        group=str(persona.group),
        repeat_index=repeat_index,
        expected=dict(persona.expected.fields),
        actual=actual_fields,
        passed=passed,
        field_accuracy=accuracy.accuracy,
        handoff_expected=persona.expected.handoff,
        handoff_actual=handoff_actual,
        fallback_activated=fallback_activated,
        outcome_expected=persona.expected.outcome,
        outcome_actual=outcome_actual,
        handle_time_s=elapsed,
        turns=caller.turns_taken,
        crm_completeness=metrics.crm_completeness(actual_fields) if persona.expects_a_lead else 1.0,
        missed_fields=accuracy.missed,
        transcript=list(caller.transcript),
        error=error,
    )


def summarise(results: Sequence[ScenarioResult], repeats: int) -> metrics.RunSummary:
    """Aggregate a run, per category and overall, always with the spread."""
    if not results:
        return metrics.RunSummary()

    scenario_ids = {r.scenario_id for r in results}
    passes_by_scenario: dict[str, list[bool]] = {}
    for result in results:
        passes_by_scenario.setdefault(result.scenario_id, []).append(result.passed)

    summary = metrics.RunSummary(
        scenarios=len(scenario_ids),
        repeats=repeats,
        passed=sum(r.passed for r in results),
        field_accuracy=metrics.spread([r.field_accuracy for r in results]),
        outcome_accuracy=metrics.spread([float(r.outcome_correct) for r in results]),
        crm_completeness=metrics.spread([r.crm_completeness for r in results]),
        handle_time_turns=metrics.spread([float(r.turns) for r in results]),
        handoff=metrics.handoff_counts([(r.handoff_expected, r.handoff_actual) for r in results]),
        fallback=metrics.fallback_activation(
            [
                (bool(r.expected.get("objections")) or _has_objection(r), r.fallback_activated)
                for r in results
            ]
        ),
        flaky=metrics.flaky_scenarios(passes_by_scenario),
    )

    for group in sorted({r.group for r in results}):
        rows = [r for r in results if r.group == group]
        summary.by_group[group] = {
            "scenarios": len({r.scenario_id for r in rows}),
            "pass_rate": sum(r.passed for r in rows) / len(rows),
            "field_accuracy": metrics.spread([r.field_accuracy for r in rows]).mean,
            "handoff_recall": metrics.handoff_counts(
                [(r.handoff_expected, r.handoff_actual) for r in rows]
            ).recall,
        }
    return summary


def _has_objection(result: ScenarioResult) -> bool:
    """Whether the persona was written to raise an objection at all."""
    return result.group in {"price_objectors", "fear_hesitation"}


def format_summary(summary: metrics.RunSummary, run_name: str, run_id: int | None) -> str:
    """The table printed at the end of a run. Numbers only, never a verdict."""
    lines = [
        "",
        f"run: {run_name}" + (f"  (id {run_id})" if run_id else ""),
        f"scenarios: {summary.scenarios}   repeats: {summary.repeats}",
        "",
        f"pass rate         {summary.pass_rate:.1%}  "
        f"({summary.passed}/{summary.scenarios * summary.repeats})",
        f"field accuracy    {summary.field_accuracy}",
        f"outcome accuracy  {summary.outcome_accuracy}",
        f"crm completeness  {summary.crm_completeness}",
        f"turns per call    {summary.handle_time_turns}",
        "",
        f"handoff precision {summary.handoff.precision:.3f}   "
        f"recall {summary.handoff.recall:.3f}   f1 {summary.handoff.f1:.3f}",
        f"  tp {summary.handoff.true_positive}  fp {summary.handoff.false_positive}  "
        f"tn {summary.handoff.true_negative}  fn {summary.handoff.false_negative}",
        "",
        f"fallback activation  {summary.fallback.get('activation_rate', 0):.3f}"
        f"   true {summary.fallback.get('true_activation_rate', 0):.3f}"
        f"   false {summary.fallback.get('false_activation_rate', 0):.3f}",
        "",
        "by group:",
    ]
    for group, values in summary.by_group.items():
        lines.append(
            f"  {group:<18} n={int(values['scenarios']):<3} "
            f"pass {values['pass_rate']:.1%}   "
            f"fields {values['field_accuracy']:.3f}   "
            f"handoff recall {values['handoff_recall']:.3f}"
        )
    lines.append("")
    lines.append(
        f"flaky scenarios ({len(summary.flaky)}): "
        + (", ".join(summary.flaky) if summary.flaky else "none")
    )
    return "\n".join(lines)
