#!/usr/bin/env python3
"""Generate the embedded V2 lessor scenario-builder dashboard payload."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aircraft_cashflow.scenario_builder import build_scenario_payload  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static-root", type=Path, default=ROOT / "dashboard" / "v2")
    args = parser.parse_args()
    payload = build_scenario_payload(
        calculated_at=datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc)
    )
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    args.static_root.mkdir(parents=True, exist_ok=True)
    (args.static_root / "dashboard-data.json").write_text(serialized + "\n", encoding="utf-8")
    (args.static_root / "dashboard-data.js").write_text(
        "window.V2_DASHBOARD_DATA = " + serialized + ";\n", encoding="utf-8"
    )
    print(args.static_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
