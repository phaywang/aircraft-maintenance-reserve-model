#!/usr/bin/env python3
"""Generate the embedded V2 lessor scenario-builder dashboard payload."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aircraft_cashflow.scenario_builder import (  # noqa: E402
    build_scenario_payload,
    default_scenario_input,
)


def _demo_inputs() -> list[dict[str, object]]:
    """Return three deterministic lifecycle paths for the hosted comparison demo."""

    base = default_scenario_input()
    variants: list[tuple[str, str, str, str]] = [
        ("base-plan", "Current lease and follow-on plan", "250", "95"),
        ("lower-utilization", "Lower-utilization follow-on", "210", "80"),
        ("higher-utilization", "Higher-utilization follow-on", "300", "110"),
    ]
    scenarios: list[dict[str, object]] = []
    for scenario_id, name, monthly_fh, monthly_fc in variants:
        scenario = deepcopy(base)
        scenario["scenario_id"] = scenario_id
        scenario["name"] = name
        follow_on = scenario["segments"][1]
        follow_on["monthly_fh"] = monthly_fh
        follow_on["monthly_fc"] = monthly_fc
        scenarios.append(scenario)
    return scenarios


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static-root", type=Path, default=ROOT / "dashboard" / "v2")
    args = parser.parse_args()
    calculated_at = datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc)
    results = [
        build_scenario_payload(scenario, calculated_at=calculated_at)
        for scenario in _demo_inputs()
    ]
    payload = deepcopy(results[0])
    payload["demo_scenarios"] = [
        {
            "input": result["scenario_input"],
            "result": result,
            "included": True,
        }
        for result in results
    ]
    # Keep the embedded hosted payload compact: it contains three complete,
    # auditable forecasts and is downloaded directly by the browser.
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    args.static_root.mkdir(parents=True, exist_ok=True)
    (args.static_root / "dashboard-data.json").write_text(serialized + "\n", encoding="utf-8")
    (args.static_root / "dashboard-data.js").write_text(
        "window.V2_DASHBOARD_DATA = " + serialized + ";\n", encoding="utf-8"
    )
    print(args.static_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
