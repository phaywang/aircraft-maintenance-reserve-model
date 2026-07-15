#!/usr/bin/env python3
"""Generate an inspectable demonstration dashboard payload without HTTP."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aircraft_cashflow.config import build_default_case  # noqa: E402
from aircraft_cashflow.dashboard_service import run_dashboard_case  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "dashboard_demo_payload.json",
    )
    parser.add_argument(
        "--static-root",
        type=Path,
        help="Also refresh the dashboard's embedded JSON and JavaScript payloads.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run_dashboard_case(build_default_case())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    args.output.write_text(serialized + "\n", encoding="utf-8")
    if args.static_root:
        args.static_root.mkdir(parents=True, exist_ok=True)
        for filename in ("dashboard-data.json", "demo-payload.json"):
            (args.static_root / filename).write_text(serialized + "\n", encoding="utf-8")
        (args.static_root / "dashboard-data.js").write_text(
            "window.DASHBOARD_DATA = " + serialized + ";\n", encoding="utf-8"
        )
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
