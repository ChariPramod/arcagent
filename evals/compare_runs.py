"""Compare two eval runs.

    python -m evals.compare_runs 3 7

Prints per metric deltas and per scenario pass changes, and flags regressions in the
categories named in ``REGRESSION_GUARDS``. Exits non zero when a guard is breached, so it
can gate a merge rather than just inform one.

The merge rule, from scope 7.3: a change that lowers handoff recall on hot buyers is not
merged, even if it raises the overall pass rate. Losing a hot lead costs more than the
average looks like it saves.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from arcagent.logging import configure_logging
from arcagent.persistence.db import session_scope
from arcagent.persistence.models import EvalResult, EvalRun, Tier
from arcagent.persistence.repo import EvalRepository
from evals import metrics
from evals.snapshots import RunSnapshot

# Metrics that must not go down, per group. The first is the merge rule.
REGRESSION_GUARDS: dict[str, tuple[str, ...]] = {
    "handoff_recall": ("hot_buyers",),
    "field_accuracy": ("hot_buyers", "price_objectors"),
}

# Anything smaller than this is noise at these sample sizes, not a regression.
NOISE_FLOOR = 0.01


@dataclass(frozen=True, slots=True)
class MetricDelta:
    name: str
    before: float
    after: float

    @property
    def delta(self) -> float:
        return self.after - self.before

    @property
    def moved(self) -> bool:
        return abs(self.delta) >= NOISE_FLOOR

    def __str__(self) -> str:
        arrow = "  " if not self.moved else ("up" if self.delta > 0 else "DOWN")
        return (
            f"  {self.name:<24} {self.before:>7.3f} -> {self.after:>7.3f}"
            f"  {self.delta:+.3f} {arrow}"
        )


def _by_group(results: Sequence[EvalResult], groups: dict[str, str]) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for row in results:
        grouped.setdefault(groups.get(row.scenario_id, "unknown"), []).append(row)
    return grouped


def _metrics_for(rows: Sequence[EvalResult]) -> dict[str, float]:
    if not rows:
        return dict.fromkeys(
            (
                "pass_rate",
                "field_accuracy",
                "handoff_recall",
                "handoff_precision",
                "crm_completeness",
            ),
            0.0,
        )
    counts = metrics.handoff_counts(
        [(bool(r.handoff_expected), bool(r.handoff_actual)) for r in rows]
    )
    return {
        "pass_rate": sum(bool(r.passed) for r in rows) / len(rows),
        "field_accuracy": metrics.spread([r.field_accuracy or 0.0 for r in rows]).mean,
        "handoff_recall": counts.recall,
        "handoff_precision": counts.precision,
        "crm_completeness": metrics.spread([r.crm_completeness or 0.0 for r in rows]).mean,
    }


class InvalidComparison(ValueError):
    """The runs do not contain sufficient comparable evidence for a merge verdict."""


def validate_run(run: EvalRun, rows: Sequence[EvalResult]) -> RunSnapshot:
    """Check planned coverage, provenance and measurements before computing any deltas."""
    if run.tier != Tier.TEXT:
        raise InvalidComparison(f"run {run.id}: only text runs have qualification evidence")
    if run.snapshot is None:
        raise InvalidComparison(f"run {run.id}: missing input snapshot; rerun the evaluation")
    try:
        snapshot = RunSnapshot.model_validate(run.snapshot)
    except ValueError as exc:
        raise InvalidComparison(f"run {run.id}: malformed input snapshot") from exc
    if (
        run.prompt_version != snapshot.config.prompt_version
        or run.threshold != snapshot.config.threshold
    ):
        raise InvalidComparison(f"run {run.id}: run metadata disagrees with its snapshot")
    planned = Counter(
        {
            (scenario, repeat): 1
            for scenario in snapshot.personas
            for repeat in range(snapshot.config.repeats)
        }
    )
    observed = Counter((row.scenario_id, row.repeat_index) for row in rows)
    if planned != observed:
        raise InvalidComparison(
            f"run {run.id}: incomplete or duplicate scenario/repeat coverage "
            f"(expected {sum(planned.values())}, recorded {sum(observed.values())})"
        )
    for row in rows:
        expected = snapshot.personas[row.scenario_id].expected
        if row.expected != expected.fields or row.handoff_expected != expected.handoff:
            raise InvalidComparison(f"run {run.id}: recorded expectations disagree with snapshot")
        if row.notes:
            raise InvalidComparison(
                f"run {run.id}: scenario errors must be resolved before comparison"
            )
        if any(
            type(value) is not bool
            for value in (row.passed, row.handoff_expected, row.handoff_actual)
        ):
            raise InvalidComparison(f"run {run.id}: missing verdict or handoff measurement")
        for name in ("field_accuracy", "crm_completeness"):
            value = getattr(row, name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise InvalidComparison(f"run {run.id}: missing or invalid {name}")
    required_groups = {group for groups in REGRESSION_GUARDS.values() for group in groups}
    missing = required_groups - set(snapshot.groups.values())
    if missing:
        raise InvalidComparison(
            f"run {run.id}: missing guarded categories: {', '.join(sorted(missing))}"
        )
    for group in REGRESSION_GUARDS.get("handoff_recall", ()):
        if not any(
            p.expected.handoff and str(p.group) == group for p in snapshot.personas.values()
        ):
            raise InvalidComparison(
                f"run {run.id}: no expected handoffs in guarded category {group}"
            )
    return snapshot


def comparison_groups(
    old_run: EvalRun,
    new_run: EvalRun,
    old_rows: Sequence[EvalResult],
    new_rows: Sequence[EvalResult],
) -> dict[str, str]:
    before, after = validate_run(old_run, old_rows), validate_run(new_run, new_rows)
    if before.suite != after.suite:
        raise InvalidComparison(
            "suite changed; fixture mutations cannot be compared with owner personas"
        )
    if before.personas != after.personas or before.caller_scripts != after.caller_scripts:
        raise InvalidComparison("persona content, expectations, or caller scripts changed")
    if before.caller_prompt != after.caller_prompt:
        raise InvalidComparison("caller instructions changed")
    for name in ("caller_model", "max_turns", "repeats", "coordinator_available"):
        if getattr(before.config, name) != getattr(after.config, name):
            raise InvalidComparison(f"benchmark configuration changed: {name}")
    return before.groups


def compare(old_id: int, new_id: int) -> int:
    """Exit codes: zero for no regression, one for regression, two for invalid evidence."""
    with session_scope() as session:
        repo = EvalRepository(session)
        old_run, new_run = repo.get_run(old_id), repo.get_run(new_id)
        if old_run is None or new_run is None:
            missing = old_id if old_run is None else new_id
            print(f"run {missing} not found")
            return 2
        old_rows = repo.results_for(old_id)
        new_rows = repo.results_for(new_id)
        _print_header(old_run, new_run)

        try:
            groups = comparison_groups(old_run, new_run, old_rows, new_rows)
        except InvalidComparison as exc:
            print(f"\nCOMPARISON INVALID: {exc}")
            return 2
        print(f"  suite={old_run.snapshot['suite']}")
        old_config, new_config = old_run.snapshot["config"], new_run.snapshot["config"]
        changes = [name for name in old_config if old_config[name] != new_config[name]]
        print(f"  changed configuration: {', '.join(sorted(changes)) or 'none'}")
        changed_prompts = [
            name
            for name, value in old_run.snapshot["prompts"].items()
            if value["sha256"] != new_run.snapshot["prompts"][name]["sha256"]
        ]
        print(f"  changed prompts: {', '.join(sorted(changed_prompts)) or 'none'}")
        print("\noverall:")
        overall_before, overall_after = _metrics_for(old_rows), _metrics_for(new_rows)
        for name in sorted(overall_before):
            print(MetricDelta(name, overall_before[name], overall_after[name]))

        regressions = _print_groups(old_rows, new_rows, groups)
        _print_scenario_changes(old_rows, new_rows)

        if regressions:
            print("\nREGRESSIONS AGAINST THE MERGE RULE:")
            for line in regressions:
                print(f"  {line}")
            print("\nSee docs/scoring.md and CONTRIBUTING.md. Do not merge on this alone.")
            return 1
        print("\nno guarded metric regressed")
        return 0


def _print_header(old_run: EvalRun, new_run: EvalRun) -> None:
    print(f"comparing run {old_run.id} -> run {new_run.id}")
    print(
        f"  {old_run.id}: {old_run.run_name}  prompts={old_run.prompt_version}  "
        f"threshold={old_run.threshold}  sha={old_run.git_sha[:8]}"
    )
    print(
        f"  {new_run.id}: {new_run.run_name}  prompts={new_run.prompt_version}  "
        f"threshold={new_run.threshold}  sha={new_run.git_sha[:8]}"
    )


def _print_groups(old_rows, new_rows, groups) -> list[str]:
    regressions: list[str] = []
    old_groups = _by_group(old_rows, groups)
    new_groups = _by_group(new_rows, groups)
    for group in sorted(set(old_groups) | set(new_groups)):
        print(f"\n{group}:")
        before = _metrics_for(old_groups.get(group, []))
        after = _metrics_for(new_groups.get(group, []))
        for name in sorted(before):
            delta = MetricDelta(name, before[name], after[name])
            print(delta)
            if group in REGRESSION_GUARDS.get(name, ()) and delta.delta <= -NOISE_FLOOR:
                regressions.append(f"{name} on {group}: {delta.delta:+.3f}")
    return regressions


def _print_scenario_changes(old_rows, new_rows) -> None:
    """Only the scenarios whose verdict changed. A hundred unchanged rows help nobody."""

    def verdict(rows) -> dict[str, bool]:
        by_scenario: dict[str, list[bool]] = {}
        for row in rows:
            by_scenario.setdefault(row.scenario_id, []).append(bool(row.passed))
        return {k: all(v) for k, v in by_scenario.items()}

    before, after = verdict(old_rows), verdict(new_rows)
    fixed = sorted(s for s in set(before) & set(after) if after[s] and not before[s])
    broken = sorted(s for s in after if not after[s] and before.get(s, False))
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))

    print("\nscenario changes:")
    for label, items in (
        ("now passing", fixed),
        ("now failing", broken),
        ("new", added),
        ("gone", removed),
    ):
        print(f"  {label:<12} {', '.join(items) if items else 'none'}")


def main() -> None:
    configure_logging(level="WARNING")
    parser = argparse.ArgumentParser(description="Compare two eval runs.")
    parser.add_argument("old_run_id", type=int)
    parser.add_argument("new_run_id", type=int)
    sys.exit(compare(*vars(parser.parse_args()).values()))


if __name__ == "__main__":
    main()
