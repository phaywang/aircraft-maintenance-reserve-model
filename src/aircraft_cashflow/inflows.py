"""Step 3: escalated maintenance reserve rates and monthly inflows."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd

from .events import (
    build_forecast_maintenance_calendar,
    build_full_maintenance_calendar,
    maintenance_calendar_columns,
)
from .models import CaseInputs, ComponentConfig, ReserveBasis


def reserve_rate_column(code: str) -> str:
    return f"reserve_rate_{code}"


def reserve_inflow_column(code: str) -> str:
    return f"reserve_inflow_{code}"


def reserve_inflow_columns(case: CaseInputs) -> tuple[str, ...]:
    rates = tuple(reserve_rate_column(component.code) for component in case.components)
    inflows = tuple(
        reserve_inflow_column(component.code) for component in case.components
    )
    return maintenance_calendar_columns(case) + rates + inflows + (
        "total_reserve_inflow",
    )


def annual_escalation_periods(current_date: date, base_date: date) -> int:
    """Return the workbook's January-reset escalation period count."""

    return current_date.year - base_date.year


def escalated_reserve_rate(
    component: ComponentConfig, current_date: date
) -> Decimal:
    """Escalate a component's base reserve rate once per calendar year."""

    periods = annual_escalation_periods(
        current_date, component.reserve_rate_base_date
    )
    factor = (Decimal("1") + component.annual_reserve_escalation) ** periods
    return component.base_reserve_rate * factor


def _reserve_units(row: object, component: ComponentConfig) -> Decimal:
    if component.reserve_basis is ReserveBasis.PER_MONTH:
        return Decimal("1")
    if component.reserve_basis is ReserveBasis.PER_FLIGHT_HOUR:
        return Decimal(str(getattr(row, "fh_month")))
    if component.reserve_basis is ReserveBasis.PER_FLIGHT_CYCLE:
        return Decimal(str(getattr(row, "fc_month")))
    raise ValueError(f"unsupported reserve basis for {component.code}")


def _add_reserve_inflows(
    calendar: pd.DataFrame, case: CaseInputs, *, zero_manufacture_row: bool = False
) -> pd.DataFrame:
    frame = calendar.copy()
    rows = list(frame.itertuples(index=False))

    for component in case.components:
        rates: list[Decimal] = []
        inflows: list[Decimal] = []
        for row in rows:
            rate = escalated_reserve_rate(component, row.date)
            rates.append(rate)
            inflow = rate * _reserve_units(row, component)
            if zero_manufacture_row and row.date <= case.lease_start_date:
                inflow = Decimal("0")
            inflows.append(inflow)
        frame[reserve_rate_column(component.code)] = rates
        frame[reserve_inflow_column(component.code)] = inflows

    inflow_names = [
        reserve_inflow_column(component.code) for component in case.components
    ]
    frame["total_reserve_inflow"] = [
        sum((Decimal(str(value)) for value in values), Decimal("0"))
        for values in frame.loc[:, inflow_names].itertuples(index=False, name=None)
    ]
    return frame.loc[:, reserve_inflow_columns(case)]


def build_full_reserve_inflows(case: CaseInputs) -> pd.DataFrame:
    """Return the full timeline, with collections beginning after lease start."""

    return _add_reserve_inflows(
        build_full_maintenance_calendar(case), case, zero_manufacture_row=True
    )


def build_forecast_reserve_inflows(case: CaseInputs) -> pd.DataFrame:
    """Return the Step 3 table from analysis date through lease expiry."""

    return _add_reserve_inflows(build_forecast_maintenance_calendar(case), case)
