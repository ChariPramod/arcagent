from arcagent.console.latency import latency_report, paired_latency_comparison
from arcagent.persistence.models import Speaker, Turn


def turn(index=0, **metrics):
    return Turn(id=index + 1, turn_index=index, speaker=Speaker.AGENT, **metrics)


def test_missing_and_invalid_are_not_zero_and_coverage_is_explicit():
    report = latency_report([turn(0, llm_ttft_ms=0), turn(1), turn(2, llm_ttft_ms=-1)])
    stage = next(s for s in report["stages"] if s["key"] == "llm_ttft_ms")
    assert stage["samples"] == 1
    assert stage["missing"] == 1
    assert stage["invalid"] == 1
    assert stage["coverage"] == 1 / 3
    assert stage["p50_ms"] == 0
    assert report["turns"][2]["stages"]["llm_ttft_ms"] is None
    assert report["caller_perceived_latency_ms"] is None


def test_empty_report_and_nearest_rank_percentiles():
    assert all(s["p95_ms"] is None for s in latency_report([])["stages"])
    report = latency_report([turn(i, tts_first_byte_ms=i * 10) for i in range(20)])
    stage = next(s for s in report["stages"] if s["key"] == "tts_first_byte_ms")
    assert (stage["p50_ms"], stage["p95_ms"]) == (90, 180)


def test_caller_rows_do_not_dilute_agent_stage_coverage_or_expose_text():
    caller = Turn(id=2, turn_index=1, speaker=Speaker.CALLER, text="private", stt_final_ms=5)
    report = latency_report([caller, turn(0, llm_ttft_ms=10)])
    assert report["turns"][0]["turn_index"] == 0
    stage = next(s for s in report["stages"] if s["key"] == "llm_ttft_ms")
    assert stage["coverage"] == 1
    assert "private" not in str(report)


def test_invalid_numeric_types_are_not_accepted():
    report = latency_report([turn(llm_ttft_ms=True, tts_first_byte_ms=float("nan"))])
    assert report["turns"][0]["invalid_stages"] == ["llm_ttft_ms", "tts_first_byte_ms"]


def test_comparison_requires_complete_matching_provenance_and_unique_pairs():
    a = [turn(llm_ttft_ms=20)]
    b = [turn(llm_ttft_ms=10)]
    provenance = {
        "scenario_id": "synthetic-a",
        "input_digest": "abc",
        "measurement_version": "1",
        "environment": "fake-clock",
    }
    assert not paired_latency_comparison(a, b, {}, {})["comparable"]
    assert not paired_latency_comparison(
        a, b, provenance, {**provenance, "input_digest": "different"}
    )["comparable"]
    assert not paired_latency_comparison(a + a, b, provenance, provenance)["comparable"]
    result = paired_latency_comparison(a, b, provenance, provenance)
    assert result["comparable"]
    stage = next(s for s in result["stages"] if s["key"] == "llm_ttft_ms")
    assert stage["paired_samples"] == 1
    assert stage["delta_p50_ms"] == -10
