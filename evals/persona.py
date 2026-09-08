"""Persona loading and validation.

Personas are owner authored YAML. This module never writes one; it reads them, validates
them against the schema in ``personas/_template.yaml``, and fails loudly on a malformed
file rather than skipping it. A silently skipped persona is a scenario that quietly stops
being tested.
"""

from __future__ import annotations

import enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from arcagent.agent.state import ObjectionKind

PERSONAS_DIR = Path(__file__).parent / "personas"


class PersonaGroup(enum.StrEnum):
    HOT_BUYERS = "hot_buyers"
    PRICE_OBJECTORS = "price_objectors"
    FEAR_HESITATION = "fear_hesitation"
    LOGISTICS = "logistics"
    ADVERSARIAL = "adversarial"


class RecoversOn(enum.StrEnum):
    FINANCING = "financing"
    ACKNOWLEDGEMENT = "acknowledgement"
    NEVER = "never"


class CallbackResponse(enum.StrEnum):
    ACCEPTS = "accepts"
    DECLINES = "declines"
    ASKS_LATER = "asks_later"


class PersonaError(ValueError):
    """A persona file is missing, unreadable, or does not match the schema."""


class Behaviour(BaseModel):
    model_config = {"extra": "forbid"}

    terse: bool = True
    volunteers: list[str] = Field(default_factory=list)
    withholds: list[str] = Field(default_factory=list)
    contradicts: bool = False


class PersonaObjection(BaseModel):
    model_config = {"extra": "forbid"}

    kind: ObjectionKind
    after_turn: int = Field(default=1, ge=0)
    recovers_on: RecoversOn = RecoversOn.NEVER


class Expected(BaseModel):
    model_config = {"extra": "forbid"}

    outcome: str
    handoff: bool = False
    fields: dict[str, Any] = Field(default_factory=dict)
    not_expected: list[str] = Field(default_factory=list)


class Persona(BaseModel):
    """One scenario. Immutable once loaded."""

    model_config = {"extra": "forbid", "frozen": True}

    id: str
    group: PersonaGroup
    description: str
    background: str
    behaviour: Behaviour = Field(default_factory=Behaviour)
    objections: list[PersonaObjection] = Field(default_factory=list)
    callback_response: CallbackResponse = CallbackResponse.ACCEPTS
    expected: Expected

    @property
    def expects_a_lead(self) -> bool:
        return self.expected.outcome in {"handoff", "callback_booked"}


def load_persona(path: Path) -> Persona:
    """Read and validate one persona file.

    Raises:
        PersonaError: unreadable YAML, or a shape the harness cannot run.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PersonaError(f"{path.name}: could not be read as YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise PersonaError(f"{path.name}: expected a mapping at the top level")
    try:
        return Persona.model_validate(raw)
    except ValidationError as exc:
        raise PersonaError(f"{path.name}: {exc.error_count()} schema errors\n{exc}") from exc


def load_personas(
    directory: Path | None = None,
    groups: list[str] | None = None,
    ids: list[str] | None = None,
) -> list[Persona]:
    """Every persona in the directory, sorted by id.

    Files starting with ``_`` are skipped, which is how the template stays next to the
    real ones without being run.

    Raises:
        PersonaError: any file fails to load. One bad file fails the run rather than
            quietly shrinking the scenario set.
    """
    directory = directory or PERSONAS_DIR
    personas = [
        load_persona(path)
        for path in sorted(directory.glob("*.yaml"))
        if not path.name.startswith("_")
    ]
    seen: dict[str, str] = {}
    for persona in personas:
        if persona.id in seen:
            raise PersonaError(f"duplicate persona id {persona.id!r}")
        seen[persona.id] = persona.id
    if groups:
        wanted = set(groups)
        personas = [p for p in personas if str(p.group) in wanted]
    if ids:
        chosen = set(ids)
        personas = [p for p in personas if p.id in chosen]
    return sorted(personas, key=lambda p: p.id)


def group_counts(personas: list[Persona]) -> dict[str, int]:
    counts: dict[str, int] = {str(g): 0 for g in PersonaGroup}
    for persona in personas:
        counts[str(persona.group)] += 1
    return counts
