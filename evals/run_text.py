"""Tier 1 harness entry point.

    python -m evals.run_text --run-name baseline --repeats 3
    python -m evals.run_text --run-name after-v2 --prompts v2 --groups hot_buyers

Every run is tagged with the git sha and the prompt version, so a number in the results
table can always be traced back to the code that produced it.
"""

from __future__ import annotations

import argparse
import asyncio

from arcagent.agent.llm import AnthropicStructuredLLM
from arcagent.config import get_settings
from arcagent.logging import configure_logging, get_logger
from arcagent.persistence.db import session_scope
from arcagent.persistence.models import Tier
from arcagent.persistence.repo import EvalRepository
from evals.persona import PersonaError, load_personas
from evals.runner import ScenarioResult, format_summary, git_sha, run_scenario, summarise

log = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run the text level eval harness.")
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--repeats", type=int, default=3, help="runs per persona")
    parser.add_argument("--prompts", default=settings.prompt_version)
    parser.add_argument("--threshold", type=int, default=settings.handoff_threshold)
    parser.add_argument("--groups", nargs="*", default=None, help="limit to these groups")
    parser.add_argument("--ids", nargs="*", default=None, help="limit to these persona ids")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--no-db", action="store_true", help="print only, write nothing")
    parser.add_argument(
        "--caller-model",
        default=None,
        help="model for the simulated caller; defaults to the extraction model",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.llm_api_key:
        raise SystemExit("LLM_API_KEY is not set. Put it in .env.")

    try:
        personas = load_personas(groups=args.groups, ids=args.ids)
    except PersonaError as exc:
        raise SystemExit(f"persona error: {exc}") from exc
    if not personas:
        raise SystemExit(
            "no personas found. evals/personas/ is owner authored and is currently empty; "
            "see evals/personas/README.md"
        )

    agent_llm = AnthropicStructuredLLM(settings)
    caller_llm = AnthropicStructuredLLM(settings)
    caller_model = args.caller_model or settings.llm_model_extraction

    semaphore = asyncio.Semaphore(args.concurrency)

    async def one(persona, repeat: int) -> ScenarioResult:
        async with semaphore:
            result = await run_scenario(
                persona=persona,
                agent_llm=agent_llm,
                caller_llm=caller_llm,
                prompt_version=args.prompts,
                threshold=args.threshold,
                repeat_index=repeat,
                caller_model=caller_model,
            )
            print(
                f"  {'pass' if result.passed else 'FAIL'}  {persona.id:<32} "
                f"r{repeat}  fields {result.field_accuracy:.2f}  "
                f"outcome {result.outcome_actual}"
            )
            return result

    print(f"running {len(personas)} personas x {args.repeats} repeats")
    results = await asyncio.gather(*(one(p, r) for r in range(args.repeats) for p in personas))

    summary = summarise(results, args.repeats)
    run_id = None
    if not args.no_db:
        run_id = write_results(args, results, sha=git_sha())
    print(format_summary(summary, args.run_name, run_id))
    return run_id or 0


def write_results(args: argparse.Namespace, results, sha: str) -> int:
    """Persist the run and every scenario result. The results table is generated from this."""
    with session_scope() as session:
        repo = EvalRepository(session)
        run = repo.create_run(
            run_name=args.run_name,
            git_sha=sha,
            prompt_version=args.prompts,
            threshold=args.threshold,
            tier=Tier.TEXT,
        )
        for result in results:
            repo.add_result(
                run.id,
                scenario_id=result.scenario_id,
                repeat_index=result.repeat_index,
                expected=result.expected,
                actual=result.actual,
                passed=result.passed,
                field_accuracy=result.field_accuracy,
                handoff_expected=result.handoff_expected,
                handoff_actual=result.handoff_actual,
                fallback_activated=result.fallback_activated,
                handle_time_s=result.handle_time_s,
                crm_completeness=result.crm_completeness,
                notes=result.error,
            )
        return run.id


def main() -> None:
    configure_logging(level="WARNING")
    args = parse_args()
    run_id = asyncio.run(run(args))
    if run_id:
        print(f"\nrun id {run_id}. compare with: python -m evals.compare_runs <old> {run_id}")


if __name__ == "__main__":
    main()
