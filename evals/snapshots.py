"""Self-contained inputs for text evaluations, captured before any model calls.

Only explicitly selected settings are recorded. Credentials, infrastructure addresses and
phone numbers from Settings must never enter a snapshot. Personas remain benchmark data.
Model sampling can still vary; these snapshots preserve inputs, not deterministic outputs.
"""

from __future__ import annotations

import hashlib
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from arcagent.agent.llm import MAX_TOKENS_TURN
from arcagent.agent.prompts import load_prompt
from arcagent.config import Settings
from evals.persona import Persona
from evals.simulator import MAX_TURNS, SIMULATOR_RULES

PROMPT_NAMES = frozenset(
    {
        "system",
        "greeting",
        "confirm_treatment_interest",
        "assess_situation",
        "extract_insurance_signal",
        "capture_contact",
        "handle_objection",
    }
)
REPO_ROOT = Path(__file__).resolve().parents[1]


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PromptSnapshot(SnapshotModel):
    content: str
    sha256: str

    @model_validator(mode="after")
    def verify_hash(self) -> Self:
        if content_hash(self.content) != self.sha256:
            raise ValueError("prompt hash does not match content")
        return self


class EvalConfig(SnapshotModel):
    prompt_version: str
    threshold: int
    coordinator_available: bool
    agent_model: str
    caller_model: str
    repeats: int = Field(ge=1)
    concurrency: int = Field(ge=1)
    max_turns: int = Field(ge=1)
    max_tokens: int = Field(ge=1)


class RunSnapshot(SnapshotModel):
    schema_version: Literal[1]
    suite: Literal["owner_personas", "fixture_mutations"]
    config: EvalConfig
    personas: dict[str, Persona]
    prompts: dict[str, PromptSnapshot]
    caller_prompt: str
    caller_scripts: dict[str, list[str]] = Field(default_factory=dict)
    source_hashes: dict[str, str] = Field(min_length=1)
    runtime: dict[str, str] = Field(min_length=1)

    @model_validator(mode="after")
    def verify_inputs(self) -> Self:
        if not self.personas or any(key != p.id for key, p in self.personas.items()):
            raise ValueError("snapshot needs personas keyed by their ids")
        if set(self.prompts) != PROMPT_NAMES:
            raise ValueError("snapshot is missing required prompts")
        if self.suite == "fixture_mutations":
            if set(self.caller_scripts) != set(self.personas):
                raise ValueError("every mutation needs a caller script")
            if any(
                not lines or any(not line.strip() for line in lines)
                for lines in self.caller_scripts.values()
            ):
                raise ValueError("caller scripts must contain nonempty utterances")
        elif self.caller_scripts:
            raise ValueError("owner persona runs cannot contain scripted mutations")
        return self

    @property
    def groups(self) -> dict[str, str]:
        return {key: str(p.group) for key, p in self.personas.items()}


def capture_snapshot(
    personas: list[Persona],
    settings: Settings,
    *,
    prompt_version: str,
    threshold: int,
    repeats: int,
    concurrency: int,
    caller_model: str,
    suite: Literal["owner_personas", "fixture_mutations"] = "owner_personas",
    caller_scripts: dict[str, list[str]] | None = None,
) -> RunSnapshot:
    """Preload the same cached prompt strings the agent will use for this run."""
    if len({p.id for p in personas}) != len(personas):
        raise ValueError("duplicate persona ids")
    prompts = {}
    for name in sorted(PROMPT_NAMES):
        content = load_prompt(name, prompt_version)
        prompts[name] = PromptSnapshot(content=content, sha256=content_hash(content))
    runtime = {"python": platform.python_version()}
    for package in ("anthropic", "langgraph", "langchain-core", "pydantic"):
        try:
            runtime[package] = version(package)
        except PackageNotFoundError:
            runtime[package] = "not-installed"
    source_hashes = {
        str(path.relative_to(REPO_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for directory in ("arcagent", "evals")
        for path in sorted((REPO_ROOT / directory).rglob("*.py"))
    }
    return RunSnapshot(
        schema_version=1,
        suite=suite,
        config=EvalConfig(
            prompt_version=prompt_version,
            threshold=threshold,
            coordinator_available=settings.coordinator_available,
            agent_model=settings.llm_model,
            caller_model=caller_model,
            repeats=repeats,
            concurrency=concurrency,
            max_turns=MAX_TURNS,
            max_tokens=MAX_TOKENS_TURN,
        ),
        personas={p.id: p.model_copy(deep=True) for p in personas},
        prompts=prompts,
        caller_prompt=SIMULATOR_RULES if suite == "owner_personas" else "scripted-caller-v1",
        caller_scripts={key: list(lines) for key, lines in (caller_scripts or {}).items()},
        source_hashes=source_hashes,
        runtime=runtime,
    )


def saved_groups(raw: dict | None) -> dict[str, str]:
    """Display old or malformed snapshots as unknown, without consulting current files."""
    if raw is None:
        return {}
    try:
        return RunSnapshot.model_validate(raw).groups
    except ValueError:
        return {}


def main() -> None:
    """Export saved inputs for review without consulting current prompts or personas."""
    import argparse
    import json

    from arcagent.persistence.db import session_scope
    from arcagent.persistence.repo import EvalRepository

    parser = argparse.ArgumentParser(description="Export the input snapshot of a text eval run.")
    parser.add_argument("run_id", type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with session_scope() as session:
        run = EvalRepository(session).get_run(args.run_id)
        if run is None or run.snapshot is None:
            raise SystemExit("run is missing or has no recorded input snapshot")
        snapshot = RunSnapshot.model_validate(run.snapshot)
        exported = {
            "run_id": run.id,
            "git_sha": run.git_sha,
            "snapshot": snapshot.model_dump(mode="json"),
        }
    args.output.write_text(
        json.dumps(exported, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"exported run {args.run_id} inputs to {args.output}")


if __name__ == "__main__":
    main()
