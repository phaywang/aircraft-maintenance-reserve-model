#!/usr/bin/env python3
"""Refresh the versioned deterministic baseline for the synthetic demo."""

from __future__ import annotations

import json
import math
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aircraft_cashflow.balances import build_forecast_reserve_balances, build_full_reserve_balances  # noqa: E402
from aircraft_cashflow.config import build_default_case  # noqa: E402
from aircraft_cashflow.events import build_forecast_maintenance_calendar  # noqa: E402
from aircraft_cashflow.inflows import build_forecast_reserve_inflows  # noqa: E402
from aircraft_cashflow.utilization import build_forecast_utilization  # noqa: E402


BASELINE_PATH = (
    PROJECT_ROOT / "src" / "aircraft_cashflow" / "demo_regression_baseline.json"
)


def json_value(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "item"):
        value = value.item()  # type: ignore[union-attr]
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def main() -> int:
    case = build_default_case()
    full_balances = build_full_reserve_balances(case)
    history = full_balances.loc[
        (full_balances["date"] >= case.lease_start_date)
        & (full_balances["date"] <= case.analysis_date)
    ].copy()
    frames = {
        "stage_1": build_forecast_utilization(case),
        "stage_2": build_forecast_maintenance_calendar(case),
        "stage_3": build_forecast_reserve_inflows(case),
        "stage_4_forecast": build_forecast_reserve_balances(case),
        "stage_4_history": history,
    }
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    for stage, frame in frames.items():
        reference = baseline["stages"][stage]
        columns = list(reference["rows"][0])
        reference["rows"] = [
            {column: json_value(row[column]) for column in columns}
            for _, row in frame.iterrows()
        ]
    BASELINE_PATH.write_text(
        json.dumps(baseline, indent=2) + "\n", encoding="utf-8"
    )
    print(BASELINE_PATH.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
