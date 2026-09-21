"""Scripted delivery variants, isolated from the owner-authored persona benchmark.

List cases without credentials: python -m evals.mutations --list
Evaluate with the configured model: python -m evals.mutations --run-name delivery --repeats 3

The caller follows a fixed script, so this measures delivery robustness, not conversational
realism. Expected fields and outcomes are checked for every variant; shared wrong answers
cannot pass merely because they are consistent. No LLM authors the expected answers.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from arcagent.agent.llm import AnthropicStructuredLLM, LLMResult, SchemaT, StructuredLLM
from arcagent.agent.readiness import PromptReadinessError, require_ready_prompts
from arcagent.config import get_settings
from arcagent.logging import configure_logging
from evals.persona import Persona
from evals.run_text import write_results
from evals.runner import ScenarioResult, format_summary, git_sha, run_scenario, summarise
from evals.simulator import CallerTurn
from evals.snapshots import capture_snapshot

FIXTURES = Path(__file__).parent / "fixtures" / "mutations.yaml"


class MutationFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    persona: Persona
    utterances: list[str] = Field(min_length=1)
    correction: str = Field(min_length=1)


def load_cases(path: Path = FIXTURES) -> list[MutationFixture]:
    """Expand deterministic, meaning-preserving delivery variants from synthetic fixtures."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("mutation fixtures must be a nonempty list")
    cases = []
    seen = set()
    for value in raw:
        fixture = MutationFixture.model_validate(value)
        if fixture.persona.id in seen:
            raise ValueError("duplicate mutation fixture id")
        seen.add(fixture.persona.id)
        if any(not line.strip() for line in fixture.utterances):
            raise ValueError("mutation utterances must not be empty")
        variants = {
            "baseline": list(fixture.utterances),
            "hesitation": [f"Um... {line}" for line in fixture.utterances],
            "spacing": ["  ".join(line.split()) for line in fixture.utterances],
            "irrelevant_detail": [
                f"{line} I have my notebook here." for line in fixture.utterances
            ],
            "self_correction": [fixture.correction, *fixture.utterances[1:]],
        }
        for name, lines in variants.items():
            persona = fixture.persona.model_copy(
                deep=True,
                update={
                    "id": f"{fixture.persona.id}__{name}",
                    "description": (
                        f"Synthetic delivery mutation: {name}. {fixture.persona.description}"
                    ),
                },
            )
            cases.append(
                MutationFixture(persona=persona, utterances=lines, correction=fixture.correction)
            )
    return cases


class ScriptedCaller:
    """A deterministic caller adapter. It cannot see or manufacture agent extractions."""

    def __init__(self, utterances: list[str]) -> None:
        self._utterances = iter(utterances)

    async def complete(
        self,
        system: str,
        messages: Any,
        schema: type[SchemaT],
        model: str | None = None,
    ) -> LLMResult[SchemaT]:
        if schema is not CallerTurn:
            raise ValueError("scripted caller can only produce caller turns")
        utterance = next(self._utterances, None)
        parsed = schema.model_validate({"utterance": utterance or "", "hung_up": utterance is None})
        return LLMResult(parsed=parsed, ttft_s=0.0, total_s=0.0, raw=parsed.model_dump_json())


async def run_cases(
    cases: list[MutationFixture],
    llm: StructuredLLM,
    *,
    repeats: int,
    prompt_version: str,
    threshold: int,
    coordinator_available: bool,
) -> list[ScenarioResult]:
    if repeats < 1:
        raise ValueError("repeats must be positive")
    results = []
    for repeat in range(repeats):
        for case in cases:
            results.append(
                await run_scenario(
                    case.persona,
                    llm,
                    ScriptedCaller(case.utterances),
                    prompt_version=prompt_version,
                    threshold=threshold,
                    coordinator_available=coordinator_available,
                    repeat_index=repeat,
                    caller_model="scripted-caller-v1",
                )
            )
    return results


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    cases = await asyncio.to_thread(load_cases)
    if args.list:
        print("Synthetic delivery fixtures. Not the owner-authored benchmark.")
        for case in cases:
            print(f"{case.persona.id}: expected {case.persona.expected.outcome}")
        return 0
    if not args.run_name:
        raise SystemExit("--run-name is required unless using --list")
    if args.repeats < 1:
        raise SystemExit("repeats must be positive")
    try:
        require_ready_prompts(args.prompts)
    except PromptReadinessError as exc:
        raise SystemExit(f"prompt readiness: {exc}") from exc
    if not settings.llm_api_key:
        raise SystemExit("LLM_API_KEY is required to evaluate mutations; --list runs offline")
    snapshot = await asyncio.to_thread(
        capture_snapshot,
        [case.persona for case in cases],
        settings,
        prompt_version=args.prompts,
        threshold=args.threshold,
        repeats=args.repeats,
        concurrency=1,
        caller_model="scripted-caller-v1",
        suite="fixture_mutations",
        caller_scripts={case.persona.id: case.utterances for case in cases},
    )
    sha = git_sha()
    results = await run_cases(
        cases,
        AnthropicStructuredLLM(settings),
        repeats=args.repeats,
        prompt_version=args.prompts,
        threshold=args.threshold,
        coordinator_available=settings.coordinator_available,
    )
    run_id = None if args.no_db else write_results(args, results, sha, snapshot)
    print("Synthetic delivery robustness, not owner benchmark performance.")
    print(format_summary(summarise(results, args.repeats), args.run_name, run_id))
    for result in results:
        print(
            f"{'pass' if result.passed else 'FAIL'} {result.scenario_id} "
            f"r{result.repeat_index} missed={','.join(result.missed_fields) or 'none'} "
            f"outcome={result.outcome_actual}"
        )
    return 0 if all(result.passed for result in results) else 1


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list fixtures without model calls")
    parser.add_argument("--run-name")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--prompts", default=settings.prompt_version)
    parser.add_argument("--threshold", type=int, default=settings.handoff_threshold)
    parser.add_argument("--no-db", action="store_true")
    configure_logging(level="WARNING")
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
