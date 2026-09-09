"""Streamlit dashboard over the eval database.

    streamlit run dashboard/app.py

Read only. Nothing here writes to the database, and nothing here computes a number a
different way than evals/metrics.py does; it imports those functions so the dashboard and
the README can never disagree.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import select

from arcagent.persistence.db import session_scope
from arcagent.persistence.models import Call, EvalResult, EvalRun, Turn
from evals import metrics
from evals.snapshots import saved_groups

st.set_page_config(page_title="ArcAgent evals", layout="wide")


@st.cache_data(ttl=30)
def load_runs() -> pd.DataFrame:
    with session_scope() as session:
        rows = session.scalars(select(EvalRun).order_by(EvalRun.id.desc())).all()
        return pd.DataFrame(
            [
                {
                    "id": r.id,
                    "run_name": r.run_name,
                    "tier": str(r.tier),
                    "prompt_version": r.prompt_version,
                    "threshold": r.threshold,
                    "git_sha": (r.git_sha or "")[:8],
                    "created_at": r.created_at,
                    "suite": (r.snapshot or {}).get("suite", "unrecorded"),
                }
                for r in rows
            ]
        )


@st.cache_data(ttl=30)
def load_results(run_id: int) -> pd.DataFrame:
    with session_scope() as session:
        run = session.get(EvalRun, run_id)
        groups = saved_groups(run.snapshot if run else None)
        rows = session.scalars(
            select(EvalResult).where(EvalResult.run_id == run_id).order_by(EvalResult.id)
        ).all()
        return pd.DataFrame(
            [
                {
                    "scenario_id": r.scenario_id,
                    "group": groups.get(r.scenario_id, "unknown"),
                    "repeat": r.repeat_index,
                    "passed": bool(r.passed),
                    "field_accuracy": r.field_accuracy,
                    "handoff_expected": r.handoff_expected,
                    "handoff_actual": r.handoff_actual,
                    "fallback_activated": r.fallback_activated,
                    "crm_completeness": r.crm_completeness,
                    "handle_time_s": r.handle_time_s,
                    "latency_p50_ms": r.latency_p50_ms,
                    "latency_p95_ms": r.latency_p95_ms,
                    "expected": r.expected,
                    "actual": r.actual,
                    "transcript": r.transcript,
                    "notes": r.notes,
                }
                for r in rows
            ]
        )


def summary_metrics(results: pd.DataFrame) -> dict[str, Any]:
    pairs = list(
        zip(
            results["handoff_expected"].fillna(False),
            results["handoff_actual"].fillna(False),
            strict=False,
        )
    )
    counts = metrics.handoff_counts([(bool(a), bool(b)) for a, b in pairs])
    passes: dict[str, list[bool]] = {}
    for row in results.itertuples():
        passes.setdefault(row.scenario_id, []).append(bool(row.passed))
    return {
        "pass_rate": results["passed"].mean() if len(results) else 0.0,
        "field_accuracy": metrics.spread(results["field_accuracy"].fillna(0).tolist()),
        "crm_completeness": metrics.spread(results["crm_completeness"].fillna(0).tolist()),
        "precision": counts.precision,
        "recall": counts.recall,
        "flaky": metrics.flaky_scenarios(passes),
    }


def page_runs() -> None:
    st.header("Runs")
    runs = load_runs()
    if runs.empty:
        st.info("No eval runs yet. Run `python -m evals.run_text --run-name baseline` and refresh.")
        return
    st.dataframe(runs, width="stretch", hide_index=True)


def page_run_detail() -> None:
    runs = load_runs()
    if runs.empty:
        st.info("No eval runs yet.")
        return

    labels = {
        f"{r.id}: {r.run_name} ({r.prompt_version}, {r.git_sha})": r.id for r in runs.itertuples()
    }
    chosen = st.selectbox("Run", list(labels))
    results = load_results(labels[chosen])
    if results.empty:
        st.warning("This run has no results.")
        return

    summary = summary_metrics(results)
    columns = st.columns(5)
    columns[0].metric("Pass rate", f"{summary['pass_rate']:.1%}")
    columns[1].metric(
        "Field accuracy",
        f"{summary['field_accuracy'].mean:.3f}",
        f"+/- {summary['field_accuracy'].stdev:.3f}",
    )
    columns[2].metric("Handoff precision", f"{summary['precision']:.3f}")
    columns[3].metric("Handoff recall", f"{summary['recall']:.3f}")
    columns[4].metric("Flaky scenarios", len(summary["flaky"]))

    if (results["group"] == "unknown").any():
        st.warning("Some results have no valid input snapshot. Their categories are unknown.")

    st.subheader("By category")
    by_group = (
        results.groupby("group")
        .agg(
            scenarios=("scenario_id", "nunique"),
            pass_rate=("passed", "mean"),
            field_accuracy=("field_accuracy", "mean"),
            crm_completeness=("crm_completeness", "mean"),
        )
        .reset_index()
    )
    st.dataframe(by_group, width="stretch", hide_index=True)
    st.bar_chart(by_group.set_index("group")["pass_rate"])

    if summary["flaky"]:
        st.subheader("Flaky scenarios")
        st.caption("Pass or fail flipped between repeats. The prompt is underdetermined here.")
        st.write(summary["flaky"])

    latencies = results["latency_p50_ms"].dropna()
    if not latencies.empty:
        st.subheader("Latency")
        st.caption("Audio tier only. Milliseconds, per turn.")
        st.bar_chart(results[["latency_p50_ms", "latency_p95_ms"]].dropna())

    page_scenario_drilldown(results)


def page_scenario_drilldown(results: pd.DataFrame) -> None:
    st.subheader("Scenario detail")
    scenario = st.selectbox("Scenario", sorted(results["scenario_id"].unique()))
    rows = results[results["scenario_id"] == scenario]
    st.dataframe(
        rows[
            [
                "repeat",
                "passed",
                "field_accuracy",
                "handoff_expected",
                "handoff_actual",
                "crm_completeness",
                "notes",
            ]
        ],
        width="stretch",
        hide_index=True,
    )
    for row in rows.itertuples():
        with st.expander(f"repeat {row.repeat}: {'pass' if row.passed else 'FAIL'}"):
            conversation, fields = st.columns(2)
            with conversation:
                st.caption("Transcript")
                if row.transcript is None:
                    st.info("No transcript was recorded for this result.")
                elif not row.transcript:
                    st.info("No utterances were captured for this result.")
                else:
                    for turn in row.transcript:
                        st.caption(turn["speaker"].capitalize())
                        st.text(turn["text"])
            with fields:
                st.caption("expected")
                st.json(row.expected or {})
                st.caption("actual")
                st.json(row.actual or {})


def page_calls() -> None:
    st.header("Calls")
    st.caption("Real calls, not eval runs. Transcript text is stored; audio is not.")
    with session_scope() as session:
        calls = session.scalars(select(Call).order_by(Call.id.desc()).limit(50)).all()
        if not calls:
            st.info("No calls recorded yet.")
            return
        frame = pd.DataFrame(
            [
                {
                    "id": c.id,
                    "call_sid": c.twilio_call_sid,
                    "started_at": c.started_at,
                    "duration_s": c.duration_s,
                    "outcome": str(c.outcome) if c.outcome else None,
                    "final_node": c.final_node,
                    "language": c.language,
                }
                for c in calls
            ]
        )
        st.dataframe(frame, width="stretch", hide_index=True)

        call_id = st.selectbox("Call", frame["id"].tolist())
        turns = session.scalars(
            select(Turn).where(Turn.call_id == call_id).order_by(Turn.turn_index)
        ).all()
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "turn": t.turn_index,
                        "speaker": str(t.speaker),
                        "node": t.node_name,
                        "interrupted": t.interrupted,
                        "stt_final_ms": t.stt_final_ms,
                        "llm_ttft_ms": t.llm_ttft_ms,
                        "tts_first_byte_ms": t.tts_first_byte_ms,
                        "playback_start_ms": t.playback_start_ms,
                        "text": t.text,
                    }
                    for t in turns
                ]
            ),
            width="stretch",
            hide_index=True,
        )


PAGES = {
    "Runs": page_runs,
    "Run detail": page_run_detail,
    "Calls": page_calls,
}

st.sidebar.title("ArcAgent")
PAGES[st.sidebar.radio("Page", list(PAGES))]()
st.sidebar.caption("Read only. Numbers come from evals/metrics.py, the same code the README uses.")
