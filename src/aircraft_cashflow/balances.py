"""Step 4: historical reserve simulation, outflows, balances, and shortfalls."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd

from .events import event_count_column
from .inflows import (
    build_full_reserve_inflows,
    reserve_inflow_column,
    reserve_inflow_columns,
)
from .models import CaseInputs, ComponentConfig


def event_cost_column(code: str) -> str:
    return f"event_cost_{code}"


def opening_balance_column(code: str) -> str:
    return f"opening_balance_{code}"


def available_balance_column(code: str) -> str:
    return f"available_balance_{code}"


def reserve_outflow_column(code: str) -> str:
    return f"reserve_outflow_{code}"


def closing_balance_column(code: str) -> str:
    return f"closing_balance_{code}"


def unfunded_amount_column(code: str) -> str:
    return f"unfunded_amount_{code}"


def balance_columns(case: CaseInputs) -> tuple[str, ...]:
    component_codes = tuple(component.code for component in case.components)
    event_costs = tuple(event_cost_column(code) for code in component_codes)
    opening = tuple(opening_balance_column(code) for code in component_codes)
    available = tuple(available_balance_column(code) for code in component_codes)
    outflows = tuple(reserve_outflow_column(code) for code in component_codes)
    closing = tuple(closing_balance_column(code) for code in component_codes)
    unfunded = tuple(unfunded_amount_column(code) for code in component_codes)
    totals = (
        "total_event_cost",
        "total_reserve_outflow",
        "total_closing_balance",
        "total_unfunded_amount",
    )
    return (
        reserve_inflow_columns(case)
        + event_costs
        + opening
        + available
        + outflows
        + closing
        + unfunded
        + totals
    )


def annual_cost_escalation_periods(current_date: date, base_date: date) -> int:
    """Return the workbook's January-reset cost escalation period count."""

    return current_date.year - base_date.year


def escalated_event_cost(
    component: ComponentConfig, current_date: date
) -> Decimal:
    """Return the cost of one event at the current calendar-year level."""

    periods = annual_cost_escalation_periods(current_date, component.cost_base_date)
    factor = (Decimal("1") + component.annual_cost_escalation) ** periods
    return component.base_cost * factor


def _add_balance_rollforward(
    inflows: pd.DataFrame, case: CaseInputs
) -> pd.DataFrame:
    frame = inflows.copy()
    balances = {component.code: Decimal("0") for component in case.components}
    calculated: dict[str, list[Decimal]] = {
        column: []
        for component in case.components
        for column in (
            event_cost_column(component.code),
            opening_balance_column(component.code),
            available_balance_column(component.code),
            reserve_outflow_column(component.code),
            closing_balance_column(component.code),
            unfunded_amount_column(component.code),
        )
    }

    for row in frame.itertuples(index=False):
        for component in case.components:
            code = component.code
            opening = balances[code]
            inflow = Decimal(str(getattr(row, reserve_inflow_column(code))))
            available = opening + inflow
            event_count = int(getattr(row, event_count_column(code)))
            event_cost = escalated_event_cost(component, row.date) * event_count
            outflow = min(available, event_cost) if event_count else Decimal("0")
            closing = available - outflow
            unfunded = max(event_cost - available, Decimal("0"))

            calculated[event_cost_column(code)].append(event_cost)
            calculated[opening_balance_column(code)].append(opening)
            calculated[available_balance_column(code)].append(available)
            calculated[reserve_outflow_column(code)].append(outflow)
            calculated[closing_balance_column(code)].append(closing)
            calculated[unfunded_amount_column(code)].append(unfunded)
            balances[code] = closing

    for column, values in calculated.items():
        frame[column] = values

    def row_sum(columns: list[str]) -> list[Decimal]:
        return [
            sum((Decimal(str(value)) for value in values), Decimal("0"))
            for values in frame.loc[:, columns].itertuples(index=False, name=None)
        ]

    codes = [component.code for component in case.components]
    frame["total_event_cost"] = row_sum([event_cost_column(code) for code in codes])
    frame["total_reserve_outflow"] = row_sum(
        [reserve_outflow_column(code) for code in codes]
    )
    frame["total_closing_balance"] = row_sum(
        [closing_balance_column(code) for code in codes]
    )
    frame["total_unfunded_amount"] = row_sum(
        [unfunded_amount_column(code) for code in codes]
    )
    return frame.loc[:, balance_columns(case)]


def build_full_reserve_balances(case: CaseInputs) -> pd.DataFrame:
    """Simulate the full timeline; reserve collection starts after lease inception."""

    return _add_balance_rollforward(build_full_reserve_inflows(case), case)


def build_forecast_reserve_balances(case: CaseInputs) -> pd.DataFrame:
    """Return the Step 4 table while preserving balances simulated from history."""

    full = build_full_reserve_balances(case)
    forecast = full.loc[full["date"] >= case.analysis_date].copy()
    forecast["period"] = range(len(forecast))
    return forecast.loc[:, balance_columns(case)].reset_index(drop=True)
