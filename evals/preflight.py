"""Offline input readiness. This checks structure, not approval or conversational quality."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from arcagent.agent.readiness import inspect_prompts
from evals.persona import PersonaError, group_counts, load_personas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts", default="v1")
    parser.add_argument("--personas-dir", type=Path, default=None)
    parser.add_argument("--groups", nargs="*", default=None)
    parser.add_argument("--ids", nargs="*", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    issues = [
        {"component": "prompts", "name": issue.name, "reason": issue.reason}
        for issue in inspect_prompts(args.prompts)
    ]
    personas = []
    try:
        personas = load_personas(directory=args.personas_dir, groups=args.groups, ids=args.ids)
    except (PersonaError, OSError):
        issues.append({"component": "personas", "name": "suite", "reason": "invalid_personas"})
    else:
        if not personas:
            issues.append(
                {"component": "personas", "name": "suite", "reason": "no_selected_personas"}
            )
    report = {
        "ready": not issues,
        "scope": "input_structure_only",
        "persona_count": len(personas),
        "groups": {name: count for name, count in group_counts(personas).items() if count},
        "issues": issues,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("Inputs structurally ready" if report["ready"] else "Inputs not ready")
        print(f"Selected personas: {len(personas)}")
        for issue in issues:
            print(f"  {issue['component']}/{issue['name']}: {issue['reason']}")
        print(
            "This does not verify approved wording, independent labels, credentials, or live calls."
        )
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
