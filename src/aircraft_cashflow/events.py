"""Step 2: deterministic maintenance-event calendar."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd

from .dates import completed_months, is_month_end
from .models import CaseInputs, ComponentConfig, EventDriver
from .utilization import UTILIZATION_COLUMNS, build_full_utilization


def event_count_column(code: str) -> str:
    return f"event_count_{code}"


def event_flag_column(code: str) -> str:
    return f"event_{code}"


def maintenance_calendar_columns(case: CaseInputs) -> tuple[str, ...]:
    counts = tuple(event_count_column(component.code) for component in case.components)
    flags = tuple(event_flag_column(component.code) for component in case.components)
    return UTILIZATION_COLUMNS + counts + flags + ("mx_calendar",)


def _threshold_count(previous: Decimal, current: Decimal, interval: Decimal) -> int:
    """Count interval thresholds crossed between two cumulative values."""

    if current < previous:
        raise ValueError("cumulative maintenance driver must not decrease")
    previous_band = int(previous // interval)
    current_band = int(current // interval)
    return current_band - previous_band


def _calendar_event_counts(
    dates: list[date], case: CaseInputs, component: ComponentConfig
) -> list[int]:
    if component.interval != component.interval.to_integral_value():
        raise ValueError(
            f"calendar interval for {component.code} must be a whole number of months"
        )
    anchor = component.last_event_date or case.date_of_manufacture
    if not is_month_end(anchor):
        raise ValueError(f"calendar anchor for {component.code} must be month-end")

    interval = int(component.interval)
    counts: list[int] = []
    previous_elapsed = 0
    for current_date in dates:
        if current_date <= anchor:
            elapsed = 0
        else:
            elapsed = completed_months(anchor, current_date)
        count = elapsed // interval - previous_elapsed // interval
        counts.append(max(count, 0))
        previous_elapsed = elapsed
    return counts


def _usage_event_counts(
    timeline: pd.DataFrame, case: CaseInputs, component: ComponentConfig
) -> list[int]:
    usage_column = (
        "fh_month"
        if component.event_driver is EventDriver.FLIGHT_HOURS
        else "fc_month"
    )
    cumulative_column = (
        "ttsn" if component.event_driver is EventDriver.FLIGHT_HOURS else "tcsn"
    )

    if component.usage_since_event_at_lease_start is None:
        cumulative_values = list(timeline[cumulative_column])
        previous = Decimal("0")
        counts: list[int] = []
        for current in cumulative_values:
            current_decimal = Decimal(str(current))
            counts.append(_threshold_count(previous, current_decimal, component.interval))
            previous = current_decimal
        return counts

    running = component.usage_since_event_at_lease_start
    previous = running
    counts = []
    for row in timeline.itertuples(index=False):
        current_date = row.date
        if current_date < case.lease_start_date:
            counts.append(0)
            continue
        if current_date > case.lease_start_date:
            running += Decimal(str(getattr(row, usage_column)))
        counts.append(_threshold_count(previous, running, component.interval))
        previous = running
    return counts


def build_full_maintenance_calendar(case: CaseInputs) -> pd.DataFrame:
    """Add component event counts, flags, and labels to the full usage timeline."""

    timeline = build_full_utilization(case).copy()
    dates = list(timeline["date"])

    for component in case.components:
        if component.event_driver is EventDriver.CALENDAR_MONTHS:
            counts = _calendar_event_counts(dates, case, component)
        else:
            counts = _usage_event_counts(timeline, case, component)
        timeline[event_count_column(component.code)] = counts
        timeline[event_flag_column(component.code)] = [count > 0 for count in counts]

    labels: list[str] = []
    for row in timeline.itertuples(index=False):
        row_labels = [
            component.code
            for component in case.components
            if getattr(row, event_flag_column(component.code))
        ]
        labels.append(",".join(row_labels) if row_labels else "-")
    timeline["mx_calendar"] = labels
    return timeline.loc[:, maintenance_calendar_columns(case)]


def build_forecast_maintenance_calendar(case: CaseInputs) -> pd.DataFrame:
    """Return the Step 2 table from analysis date through lease expiry."""

    full_calendar = build_full_maintenance_calendar(case)
    forecast = full_calendar.loc[full_calendar["date"] >= case.analysis_date].copy()
    forecast["period"] = range(len(forecast))
    return forecast.loc[:, maintenance_calendar_columns(case)].reset_index(drop=True)

