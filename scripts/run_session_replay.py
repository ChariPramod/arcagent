"""Replay fixed synthetic scenarios through production CallSession without vendors."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

from evals.session_replay import compare_sessions, replay_session


async def _run(args):
    scenarios = [args.scenario] if args.scenario else ["interrupt", "disconnect", "vendor_failure"]
    results = []
    for scenario in scenarios:
        payload = {"version": 1, "scenario_id": scenario}
        if args.candidate_barge_in_min_words is not None:
            payload["candidate_config"] = {"barge_in_min_words": args.candidate_barge_in_min_words}
            results.append(await compare_sessions(payload))
        else:
            results.append(await replay_session(payload))
    passed = all(result.get("candidate", result)["passed"] for result in results)
    return {"passed": passed, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=["interrupt", "disconnect", "vendor_failure"])
    parser.add_argument("--candidate-barge-in-min-words", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        # Production logs remain visible on stderr; stdout stays machine-readable JSON.
        with redirect_stdout(sys.stderr):
            report = asyncio.run(_run(args))
        rendered = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(rendered)
        else:
            print(rendered, end="")
    except (ValueError, OSError, TimeoutError) as exc:
        parser.error(str(exc) or "Production session replay exceeded its watchdog")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
