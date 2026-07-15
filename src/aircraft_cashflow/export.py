"""Inspectable local file outputs for completed calculation stages."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .utilization import UTILIZATION_COLUMNS


def write_utilization_csv(frame: pd.DataFrame, output_path: str | Path) -> Path:
    """Write the Step 1 table without altering calculation precision."""

    missing_columns = [column for column in UTILIZATION_COLUMNS if column not in frame]
    if missing_columns:
        raise ValueError(
            "utilization output is missing columns: " + ", ".join(missing_columns)
        )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.loc[:, UTILIZATION_COLUMNS].to_csv(path, index=False)
    return path


def write_maintenance_calendar_csv(
    frame: pd.DataFrame, output_path: str | Path
) -> Path:
    """Write the complete Step 2 table with event counts, flags, and labels."""

    required = set(UTILIZATION_COLUMNS) | {"mx_calendar"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError("maintenance calendar is missing columns: " + ", ".join(missing))
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def write_reserve_inflows_csv(frame: pd.DataFrame, output_path: str | Path) -> Path:
    """Write the Step 3 table with component rates, inflows, and total inflow."""

    required = set(UTILIZATION_COLUMNS) | {"mx_calendar", "total_reserve_inflow"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError("reserve inflow output is missing columns: " + ", ".join(missing))
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def write_reserve_balances_csv(frame: pd.DataFrame, output_path: str | Path) -> Path:
    """Write the Step 4 table with costs, outflows, balances, and shortfalls."""

    required = set(UTILIZATION_COLUMNS) | {
        "mx_calendar",
        "total_reserve_inflow",
        "total_event_cost",
        "total_reserve_outflow",
        "total_closing_balance",
        "total_unfunded_amount",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError("reserve balance output is missing columns: " + ", ".join(missing))
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path

