"""V2.5 common-horizon valuation and incremental NPV comparison."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from .models import to_decimal
from .transitions import AlternativeSet, build_lifecycle_economics


VALUATION_CASHFLOW_COLUMNS = (
    "alternative_id", "alternative_name", "date", "cashflow_type",
    "nominal_cashflow", "days_from_valuation", "discount_factor",
    "present_value",
)
VALUATION_SUMMARY_COLUMNS = (
    "alternative_id", "alternative_name", "valuation_date", "common_horizon",
    "undiscounted_operating_cashflow", "net_terminal_value", "npv",
    "incremental_npv", "total_rent", "total_reserves", "total_maintenance_cost",
    "total_transition_cost",
)


@dataclass(frozen=True)
class ValuationResult:
    summary: pd.DataFrame
    discounted_cashflows: pd.DataFrame
    baseline_id: str
    annual_discount_rate: Decimal
    common_horizon: date


def _discount_factor(rate: Decimal, days: int) -> Decimal:
    if days < 0:
        raise ValueError("cash flow cannot precede valuation_date")
    return Decimal(str((1.0 + float(rate)) ** (days / 365.0)))


def compare_alternatives(
    alternatives: AlternativeSet,
    annual_discount_rate: Decimal | int | float | str,
    baseline_id: str,
    common_horizon: date,
) -> ValuationResult:
    """Value complete alternatives on one date and one economic horizon."""

    rate = to_decimal(annual_discount_rate, "annual_discount_rate")
    if rate <= Decimal("-1"):
        raise ValueError("annual_discount_rate must be greater than -100%")
    ids = {item.alternative_id for item in alternatives.alternatives}
    if baseline_id not in ids:
        raise ValueError("baseline_id must identify one alternative")

    cashflow_rows: list[dict[str, object]] = []
    summary_inputs: list[dict[str, object]] = []
    for alternative in alternatives.alternatives:
        scenario = alternative.scenario
        if scenario.comparison_horizon != common_horizon:
            raise ValueError(
                f"alternative {alternative.alternative_id!r} is not modeled through "
                "the common horizon"
            )
        if scenario.terminal_value is None:
            raise ValueError(
                f"alternative {alternative.alternative_id!r} requires terminal value"
            )
        economics = build_lifecycle_economics(scenario)
        operating_npv = Decimal("0")
        for row in economics.cashflows.itertuples(index=False):
            if row.date < scenario.valuation_date:
                continue
            days = (row.date - scenario.valuation_date).days
            factor = _discount_factor(rate, days)
            nominal = Decimal(str(row.net_owner_cashflow))
            present_value = nominal / factor
            operating_npv += present_value
            cashflow_rows.append({
                "alternative_id": alternative.alternative_id,
                "alternative_name": alternative.name,
                "date": row.date,
                "cashflow_type": "operating",
                "nominal_cashflow": nominal,
                "days_from_valuation": days,
                "discount_factor": factor,
                "present_value": present_value,
            })
        terminal = scenario.terminal_value.amount - scenario.terminal_value.selling_cost
        terminal_days = (common_horizon - scenario.valuation_date).days
        terminal_factor = _discount_factor(rate, terminal_days)
        terminal_pv = terminal / terminal_factor
        cashflow_rows.append({
            "alternative_id": alternative.alternative_id,
            "alternative_name": alternative.name,
            "date": common_horizon,
            "cashflow_type": "terminal_value",
            "nominal_cashflow": terminal,
            "days_from_valuation": terminal_days,
            "discount_factor": terminal_factor,
            "present_value": terminal_pv,
        })
        cash = economics.cashflows
        summary_inputs.append({
            "alternative_id": alternative.alternative_id,
            "alternative_name": alternative.name,
            "valuation_date": scenario.valuation_date,
            "common_horizon": common_horizon,
            "undiscounted_operating_cashflow": sum(cash["net_owner_cashflow"], Decimal("0")),
            "net_terminal_value": terminal,
            "npv": operating_npv + terminal_pv,
            "total_rent": sum(cash["rent_inflow"], Decimal("0")),
            "total_reserves": sum(cash["maintenance_reserve_inflow"], Decimal("0")),
            "total_maintenance_cost": sum(cash["maintenance_cost"], Decimal("0")),
            "total_transition_cost": sum(cash["transition_cost"], Decimal("0")),
        })
    baseline_npv = next(
        row["npv"] for row in summary_inputs if row["alternative_id"] == baseline_id
    )
    for row in summary_inputs:
        row["incremental_npv"] = row["npv"] - baseline_npv
    return ValuationResult(
        pd.DataFrame(summary_inputs, columns=VALUATION_SUMMARY_COLUMNS),
        pd.DataFrame(cashflow_rows, columns=VALUATION_CASHFLOW_COLUMNS),
        baseline_id, rate, common_horizon,
    )
