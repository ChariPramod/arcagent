"""Run comparison and the merge rule it enforces."""

from __future__ import annotations

from pathlib import Path

import pytest

from arcagent.persistence.db import get_engine, get_session_factory
from arcagent.persistence.models import Base, Tier
from arcagent.persistence.repo import EvalRepository
from evals.compare_runs import NOISE_FLOOR, REGRESSION_GUARDS, MetricDelta, _metrics_for


class Row:
    """The subset of an EvalResult the comparison reads."""

    def __init__(
        self,
        passed=True,
        field_accuracy=1.0,
        handoff_expected=True,
        handoff_actual=True,
        crm_completeness=1.0,
        scenario_id="s",
    ):
        self.passed = passed
        self.field_accuracy = field_accuracy
        self.handoff_expected = handoff_expected
        self.handoff_actual = handoff_actual
        self.crm_completeness = crm_completeness
        self.scenario_id = scenario_id


class TestMetricDelta:
    def test_a_small_move_is_noise_not_a_change(self) -> None:
        assert not MetricDelta("x", 0.900, 0.9005).moved

    def test_a_real_move_is_reported(self) -> None:
        delta = MetricDelta("handoff_recall", 0.95, 0.80)
        assert delta.moved
        assert delta.delta == pytest.approx(-0.15)
        assert "DOWN" in str(delta)

    def test_an_improvement_is_marked_up(self) -> None:
        assert "up" in str(MetricDelta("pass_rate", 0.5, 0.9))


class TestGroupMetrics:
    def test_an_empty_group_does_not_divide_by_zero(self) -> None:
        assert _metrics_for([]) == {
            "pass_rate": 0.0,
            "field_accuracy": 0.0,
            "handoff_recall": 0.0,
        }

    def test_recall_falls_when_a_handoff_is_missed(self) -> None:
        before = _metrics_for([Row(), Row()])
        after = _metrics_for([Row(), Row(handoff_actual=False, passed=False)])
        assert before["handoff_recall"] == 1.0
        assert after["handoff_recall"] == 0.5


class TestMergeRule:
    def test_hot_buyer_handoff_recall_is_guarded(self) -> None:
        """The merge rule from scope 7.3. If this stops being guarded, the rule is gone."""
        assert "hot_buyers" in REGRESSION_GUARDS["handoff_recall"]

    def test_the_noise_floor_is_documented_and_small(self) -> None:
        assert 0 < NOISE_FLOOR <= 0.05


class TestComparisonAgainstTheDatabase:
    def _run(self, session, name: str, rows: list[dict]) -> int:
        repo = EvalRepository(session)
        run = repo.create_run(name, "sha", "v1", 60, Tier.TEXT)
        for row in rows:
            repo.add_result(run.id, **row)
        session.commit()
        return run.id

    def test_a_regression_in_the_guarded_metric_exits_non_zero(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        url = f"sqlite:///{tmp_path / 'compare.db'}"
        Base.metadata.create_all(get_engine(url))
        session = get_session_factory(url)()
        try:
            good = [
                {
                    "scenario_id": "hot_1",
                    "passed": True,
                    "field_accuracy": 1.0,
                    "handoff_expected": True,
                    "handoff_actual": True,
                    "crm_completeness": 1.0,
                },
            ]
            bad = [
                {
                    "scenario_id": "hot_1",
                    "passed": False,
                    "field_accuracy": 0.5,
                    "handoff_expected": True,
                    "handoff_actual": False,
                    "crm_completeness": 0.5,
                },
            ]
            old_id = self._run(session, "before", good)
            new_id = self._run(session, "after", bad)
        finally:
            session.close()

        import evals.compare_runs as module

        monkeypatch.setattr(module, "session_scope", lambda *a, **k: _scope(url))
        monkeypatch.setattr(module, "scenario_groups", lambda rows: {"hot_1": "hot_buyers"})
        assert module.compare(old_id, new_id) == 1

    def test_an_improvement_exits_zero(self, tmp_path: Path, monkeypatch) -> None:
        url = f"sqlite:///{tmp_path / 'compare_ok.db'}"
        Base.metadata.create_all(get_engine(url))
        session = get_session_factory(url)()
        try:
            old_id = self._run(
                session,
                "before",
                [
                    {
                        "scenario_id": "hot_1",
                        "passed": False,
                        "field_accuracy": 0.5,
                        "handoff_expected": True,
                        "handoff_actual": False,
                        "crm_completeness": 0.5,
                    },
                ],
            )
            new_id = self._run(
                session,
                "after",
                [
                    {
                        "scenario_id": "hot_1",
                        "passed": True,
                        "field_accuracy": 1.0,
                        "handoff_expected": True,
                        "handoff_actual": True,
                        "crm_completeness": 1.0,
                    },
                ],
            )
        finally:
            session.close()

        import evals.compare_runs as module

        monkeypatch.setattr(module, "session_scope", lambda *a, **k: _scope(url))
        monkeypatch.setattr(module, "scenario_groups", lambda rows: {"hot_1": "hot_buyers"})
        assert module.compare(old_id, new_id) == 0

    def test_a_missing_run_is_reported_not_crashed(self, tmp_path: Path, monkeypatch) -> None:
        url = f"sqlite:///{tmp_path / 'compare_missing.db'}"
        Base.metadata.create_all(get_engine(url))
        import evals.compare_runs as module

        monkeypatch.setattr(module, "session_scope", lambda *a, **k: _scope(url))
        assert module.compare(1, 2) == 2


def _scope(url: str):
    from contextlib import contextmanager

    from arcagent.persistence.db import session_scope

    @contextmanager
    def wrapped():
        with session_scope(url) as session:
            yield session

    return wrapped()


class TestResultsRenderer:
    def test_no_runs_writes_a_placeholder_not_a_stale_number(self, tmp_path: Path) -> None:
        from scripts.render_eval_results import EMPTY

        assert "No eval runs" in EMPTY
        assert "DO NOT EDIT BY HAND" in EMPTY

    def test_the_rendered_table_carries_the_sha_and_prompt_version(self) -> None:
        from types import SimpleNamespace

        from scripts.render_eval_results import render_run

        run = SimpleNamespace(
            id=7,
            run_name="baseline",
            git_sha="abc1234def",
            prompt_version="v1",
            threshold=60,
            tier="text",
            created_at=None,
        )
        rows = [
            SimpleNamespace(
                scenario_id="hot_1",
                passed=True,
                field_accuracy=1.0,
                handoff_expected=True,
                handoff_actual=True,
                crm_completeness=1.0,
            ),
            SimpleNamespace(
                scenario_id="hot_1",
                passed=False,
                field_accuracy=0.5,
                handoff_expected=True,
                handoff_actual=False,
                crm_completeness=0.5,
            ),
        ]
        markdown = render_run(run, rows, {"hot_1": "hot_buyers"})
        assert "abc1234def" in markdown
        assert "prompt version: `v1`" in markdown
        assert "DO NOT EDIT BY HAND" in markdown
        assert "+/-" in markdown  # spread, never a bare mean
        assert "`hot_1`" in markdown  # flaky, since it flipped between repeats
