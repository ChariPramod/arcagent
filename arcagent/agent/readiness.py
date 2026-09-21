"""Fail-closed readiness checks for the effective, cached prompt bundle."""

import re
from dataclasses import dataclass

from arcagent.agent.prompts import PromptNotFound, load_prompt

REQUIRED_PROMPTS = frozenset(
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


@dataclass(frozen=True, slots=True)
class PromptIssue:
    name: str
    reason: str


class PromptReadinessError(ValueError):
    def __init__(self, issues: list[PromptIssue]):
        self.issues = issues
        super().__init__(
            "Prompt bundle is not ready: "
            + ", ".join(f"{issue.name}:{issue.reason}" for issue in issues)
        )


def inspect_prompts(version: str) -> list[PromptIssue]:
    """Return safe names and codes, never prompt content, paths or filesystem errors."""
    if not re.fullmatch(r"v[0-9]+", version):
        return [PromptIssue("version", "invalid_version")]
    issues = []
    for name in sorted(REQUIRED_PROMPTS):
        try:
            content = load_prompt(name, version)
        except PromptNotFound:
            issues.append(PromptIssue(name, "missing"))
            continue
        except (OSError, UnicodeError):
            issues.append(PromptIssue(name, "unreadable"))
            continue
        if not content.strip():
            issues.append(PromptIssue(name, "empty"))
        elif "todo_owner" in content.casefold():
            issues.append(PromptIssue(name, "placeholder"))
    return issues


def require_ready_prompts(version: str) -> None:
    issues = inspect_prompts(version)
    if issues:
        raise PromptReadinessError(issues)
