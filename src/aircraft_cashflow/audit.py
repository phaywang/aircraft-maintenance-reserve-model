"""Runtime integrity and deterministic demo regression validation."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from .balances import (
    available_balance_column,
    closing_balance_column,
    event_cost_column,
    opening_balance_column,
    reserve_outflow_column,
    unfunded_amount_column,
)
from .config import build_default_case
from .inflows import reserve_inflow_column
from .models import CaseInputs


DEMO_BASELINE_PATH = Path(__file__).with_name("demo_regression_baseline.json")
MAX_FAILURE_DETAILS = 20


CHECK_DEFINITIONS = {
    "available_balance_tie_out": (
        "Available reserve tie-out",
        "Available reserve equals opening balance plus current-period inflow.",
    ),
    "opening_continuity": (
        "Opening balance continuity",
        "Each component opening balance equals its prior-month closing balance.",
    ),
    "reimbursement_lower_of": (
        "Exact lower-of reimbursement",
        "Event outflow equals the lower of component reserve available and event cost.",
    ),
    "rollforward_tie_out": (
        "Closing balance roll-forward",
        "Closing balance equals opening balance plus inflow less outflow.",
    ),
    "shortfall_tie_out": (
        "Funding shortfall tie-out",
        "Shortfall equals event cost less reserve available, floored at zero.",
    ),
    "nonnegative_balances": (
        "Nonnegative reserve balances",
        "Available reserve, outflow, closing balance and shortfall remain nonnegative.",
    ),
    "component_totals_tie_out": (
        "Component totals tie-out",
        "Reported totals equal the sum of the five segregated component accounts.",
    ),
}


def _display(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def build_runtime_checks(
    full_balances: pd.DataFrame, case: CaseInputs
) -> dict[str, dict[str, object]]:
    """Validate the complete lease-period history and forecast roll-forward."""

    lease = full_balances.loc[
        (full_balances["date"] >= case.lease_start_date)
        & (full_balances["date"] <= case.lease_expiry_date)
    ].reset_index(drop=True)
    checks: dict[str, dict[str, object]] = {
        key: {
            "label": label,
            "description": description,
            "checks": 0,
            "passed_checks": 0,
            "failures": [],
        }
        for key, (label, description) in CHECK_DEFINITIONS.items()
    }

    def record(
        key: str,
        passed: bool,
        current_date: date,
        component: str,
        expected: object,
        actual: object,
    ) -> None:
        result = checks[key]
        result["checks"] = int(result["checks"]) + 1
        if passed:
            result["passed_checks"] = int(result["passed_checks"]) + 1
            return
        failures = result["failures"]
        if isinstance(failures, list) and len(failures) < MAX_FAILURE_DETAILS:
            failure = {
                "date": current_date,
                "component": component,
                "expected": _display(expected),
                "actual": _display(actual),
            }
            if isinstance(expected, Decimal) and isinstance(actual, Decimal):
                failure["difference"] = str(actual - expected)
            failures.append(failure)

    previous_closing: dict[str, Decimal] = {}
    for row in lease.itertuples(index=False):
        for component in case.components:
            code = component.code
            opening = Decimal(str(getattr(row, opening_balance_column(code))))
            inflow = Decimal(str(getattr(row, reserve_inflow_column(code))))
            available = Decimal(str(getattr(row, available_balance_column(code))))
            cost = Decimal(str(getattr(row, event_cost_column(code))))
            outflow = Decimal(str(getattr(row, reserve_outflow_column(code))))
            closing = Decimal(str(getattr(row, closing_balance_column(code))))
            shortfall = Decimal(str(getattr(row, unfunded_amount_column(code))))

            expected_available = opening + inflow
            expected_outflow = min(available, cost)
            expected_closing = opening + inflow - outflow
            expected_shortfall = max(cost - available, Decimal("0"))
            record(
                "available_balance_tie_out",
                available == expected_available,
                row.date,
                code,
                expected_available,
                available,
            )
            if code in previous_closing:
                record(
                    "opening_continuity",
                    opening == previous_closing[code],
                    row.date,
                    code,
                    previous_closing[code],
                    opening,
                )
            record(
                "reimbursement_lower_of",
                outflow == expected_outflow,
                row.date,
                code,
                expected_outflow,
                outflow,
            )
            record(
                "rollforward_tie_out",
                closing == expected_closing,
                row.date,
                code,
                expected_closing,
                closing,
            )
            record(
                "shortfall_tie_out",
                shortfall == expected_shortfall,
                row.date,
                code,
                expected_shortfall,
                shortfall,
            )
            record(
                "nonnegative_balances",
                min(available, outflow, closing, shortfall) >= 0,
                row.date,
                code,
                "all values >= 0",
                min(available, outflow, closing, shortfall),
            )
            previous_closing[code] = closing

        total_specs = {
            "event cost": (
                "total_event_cost",
                [event_cost_column(component.code) for component in case.components],
            ),
            "reserve outflow": (
                "total_reserve_outflow",
                [reserve_outflow_column(component.code) for component in case.components],
            ),
            "closing balance": (
                "total_closing_balance",
                [closing_balance_column(component.code) for component in case.components],
            ),
            "shortfall": (
                "total_unfunded_amount",
                [unfunded_amount_column(component.code) for component in case.components],
            ),
        }
        for label, (total_column, component_columns) in total_specs.items():
            expected_total = sum(
                (Decimal(str(getattr(row, column))) for column in component_columns),
                Decimal("0"),
            )
            actual_total = Decimal(str(getattr(row, total_column)))
            record(
                "component_totals_tie_out",
                actual_total == expected_total,
                row.date,
                label,
                expected_total,
                actual_total,
            )

    for result in checks.values():
        result["passed"] = result["passed_checks"] == result["checks"]
    return checks


def _compare_value(actual: object, expected: object, tolerance: Decimal) -> tuple[bool, Decimal | None]:
    if expected is None and isinstance(actual, (Decimal, int, float)):
        difference = abs(Decimal(str(actual)))
        return difference <= tolerance, difference
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        difference = abs(Decimal(str(actual)) - Decimal(str(expected)))
        return difference <= tolerance, difference
    if isinstance(actual, date):
        actual = actual.isoformat()
    return str(actual) == str(expected), None


def build_demo_reconciliation(
    demo_case: bool,
    frames: dict[str, pd.DataFrame],
) -> dict[str, object]:
    """Compare the default demonstration with its versioned regression snapshot."""

    baseline = json.loads(DEMO_BASELINE_PATH.read_text(encoding="utf-8"))
    result: dict[str, object] = {
        "applicable": demo_case,
        "scenario_name": baseline["scenario_name"],
        "evidence": "Versioned deterministic regression snapshot",
        "numeric_tolerance": baseline["numeric_tolerance"],
        "stages": {},
    }
    if not demo_case:
        result.update(
            {
                "status": "not_applicable",
                "reason": "Inputs differ from the default demonstration scenario",
            }
        )
        return result

    tolerance = Decimal(baseline["numeric_tolerance"])
    all_matched = True
    stage_results: dict[str, object] = {}
    for stage, reference in baseline["stages"].items():
        frame = frames[stage].reset_index(drop=True)
        expected_rows = reference["rows"]
        columns = list(expected_rows[0]) if expected_rows else []
        matched_rows = 0
        max_difference = Decimal("0")
        failures: list[dict[str, object]] = []
        for index, expected_row in enumerate(expected_rows):
            if index >= len(frame):
                failures.append({"row": index + 1, "issue": "missing model row"})
                continue
            actual_row = frame.iloc[index]
            row_matched = True
            for column in columns:
                matched, difference = _compare_value(
                    actual_row[column], expected_row[column], tolerance
                )
                if difference is not None:
                    max_difference = max(max_difference, difference)
                if not matched:
                    row_matched = False
                    if len(failures) < MAX_FAILURE_DETAILS:
                        failures.append(
                            {
                                "row": index + 1,
                                "date": _display(actual_row.get("date")),
                                "column": column,
                                "expected": expected_row[column],
                                "actual": _display(actual_row[column]),
                                "difference": str(difference) if difference is not None else None,
                            }
                        )
            matched_rows += int(row_matched)
        if len(frame) != len(expected_rows) and len(failures) < MAX_FAILURE_DETAILS:
            failures.append(
                {
                    "issue": "row count mismatch",
                    "expected": len(expected_rows),
                    "actual": len(frame),
                }
            )
        matched = matched_rows == len(expected_rows) and len(frame) == len(expected_rows)
        all_matched = all_matched and matched
        stage_results[stage] = {
            "matched": matched,
            "matched_rows": matched_rows,
            "snapshot_rows": len(expected_rows),
            "checked_columns": len(columns),
            "max_numeric_difference": max_difference,
            "dataset": reference["dataset"],
            "failures": failures,
        }
    result.update(
        {
            "status": "matched" if all_matched else "failed",
            "reason": (
                "Model outputs match the versioned demonstration snapshot"
                if all_matched
                else "One or more model outputs differ from the demonstration snapshot"
            ),
            "stages": stage_results,
        }
    )
    return result


def _flatten_inputs(value: object, prefix: str = "") -> dict[str, object]:
    if isinstance(value, dict):
        flattened: dict[str, object] = {}
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten_inputs(item, path))
        return flattened
    if isinstance(value, list):
        flattened = {}
        for index, item in enumerate(value):
            token = (
                str(item.get("code"))
                if isinstance(item, dict) and item.get("code")
                else str(index + 1)
            )
            path = f"{prefix}.{token}" if prefix else token
            flattened.update(_flatten_inputs(item, path))
        return flattened
    return {prefix: value}


def build_input_changes(case: CaseInputs) -> list[dict[str, object]]:
    """Return scalar differences between current inputs and the default demo."""

    default = _flatten_inputs(build_default_case().to_dict())
    scenario = _flatten_inputs(case.to_dict())
    changes: list[dict[str, object]] = []
    for field in sorted(set(default) | set(scenario)):
        default_value = default.get(field)
        scenario_value = scenario.get(field)
        if default_value != scenario_value:
            changes.append(
                {
                    "field": field,
                    "default": default_value,
                    "scenario": scenario_value,
                }
            )
    return changes
