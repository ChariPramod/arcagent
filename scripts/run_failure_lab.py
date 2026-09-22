"""Run offline policy scenarios: python -m scripts.run_failure_lab [--output path]."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.replay import replay, scenario_catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=[s["id"] for s in scenario_catalog()])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--vendor-timeout-ms", type=int)
    parser.add_argument("--transcript-timeout-ms", type=int)
    parser.add_argument("--handoff-threshold", type=int)
    args = parser.parse_args()
    config = {
        key: value
        for key in ("vendor_timeout_ms", "transcript_timeout_ms", "handoff_threshold")
        if (value := getattr(args, key)) is not None
    }
    scenarios = [args.scenario] if args.scenario else [s["id"] for s in scenario_catalog()]
    try:
        results = [replay({"scenario_id": scenario, "config": config}) for scenario in scenarios]
        report = {
            "simulated": True,
            "passed": all(r["passed"] for r in results),
            "results": results,
        }
        rendered = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output:
            # Exclusive creation protects prior evidence. No implicit directories or overwrite.
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(rendered)
        else:
            print(rendered, end="")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
