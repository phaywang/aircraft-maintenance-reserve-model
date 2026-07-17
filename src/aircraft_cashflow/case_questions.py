"""Deterministic evidence calculations for the V1 maintenance-reserve analysis."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from .balances import escalated_event_cost
from .models import CaseInputs, ComponentConfig, EventDriver
from .utilization import build_full_utilization


def _decimal(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def _analysis_driver(case: CaseInputs, component: ComponentConfig) -> Decimal:
    if component.event_driver is not EventDriver.FLIGHT_HOURS:
        raise ValueError("engine interval sensitivity requires a flight-hour component")
    full = build_full_utilization(case)
    if component.usage_since_event_at_lease_start is None:
        row = full.loc[full["date"] == case.analysis_date]
        if row.empty:
            raise ValueError("analysis date is missing from the utilization timeline")
        return _decimal(row.iloc[0]["ttsn"])
    history = full.loc[
        (full["date"] > case.lease_start_date)
        & (full["date"] <= case.analysis_date)
    ]
    return component.usage_since_event_at_lease_start + sum(
        (_decimal(value) for value in history["fh_month"]), Decimal("0")
    )


def calculate_next_engine_interval_sensitivity(
    case: CaseInputs,
    base_result: dict[str, Any],
    *,
    component_code: str = "E1",
) -> list[dict[str, Any]]:
    """Reprice the next engine event at base and +/-5% current-cycle intervals.

    Historical events and the analysis-date opening reserve remain fixed. Only the
    next cycle threshold, event date, collections through that date and event cost
    are recalculated.
    """

    component = next(
        (item for item in case.components if item.code == component_code), None
    )
    if component is None:
        raise ValueError(f"component {component_code} is missing")
    current_driver = _analysis_driver(case, component)
    prior_event_driver = (current_driver // component.interval) * component.interval
    cashflows = base_result["cashflows"]
    utilization = base_result["utilization"]
    if not cashflows or not utilization:
        raise ValueError("forecast cash flow and utilization are required")
    opening_reserve = _decimal(cashflows[0][f"opening_balance_{component_code}"])

    cases = []
    for label, factor in (
        ("lower_5pct", Decimal("0.95")),
        ("base", Decimal("1")),
        ("higher_5pct", Decimal("1.05")),
    ):
        interval = component.interval * factor
        target_driver = prior_event_driver + interval
        running_driver = current_driver
        event_index = None
        for index, row in enumerate(utilization):
            if index > 0:
                running_driver += _decimal(row["fh_month"])
            if running_driver >= target_driver:
                event_index = index
                break
        evidence: dict[str, Any] = {
            "case": label,
            "engine_interval_fh": str(interval),
            "current_cycle_start_fh": str(prior_event_driver),
            "event_target_fh": str(target_driver),
            "event_in_forecast": event_index is not None,
        }
        if event_index is None:
            cases.append(evidence)
            continue
        event_row = cashflows[event_index]
        event_date = event_row["date"]
        reserve_inflow = sum(
            (
                _decimal(row[f"reserve_inflow_{component_code}"])
                for row in cashflows[: event_index + 1]
            ),
            Decimal("0"),
        )
        available = opening_reserve + reserve_inflow
        cost = escalated_event_cost(component, date.fromisoformat(event_date))
        reimbursement = min(available, cost)
        shortfall = max(cost - available, Decimal("0"))
        evidence.update({
            "event_date": event_date,
            "event_cost": str(cost),
            "available_reserve": str(available),
            "reimbursement": str(reimbursement),
            "shortfall": str(shortfall),
            "coverage_ratio": str(available / cost if cost else Decimal("0")),
        })
        cases.append(evidence)
    return cases
