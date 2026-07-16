"""V2.4 transition economics and complete alternative lifecycle packaging."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from .lifecycle import Scenario, build_contract_periods
from .settlement import SettlementResult, build_lifecycle_settlement


TRANSITION_CASHFLOW_COLUMNS = (
    "date", "transition_id", "description", "monthly_cost",
    "fixed_cost", "explicit_cost", "total_transition_cost",
)
ECONOMIC_CASHFLOW_COLUMNS = (
    "date", "rent_inflow", "maintenance_reserve_inflow", "maintenance_cost",
    "redelivery_cash_inflow", "reserve_refund_outflow", "transition_cost",
    "net_owner_cashflow",
)


@dataclass(frozen=True)
class LifecycleEconomicsResult:
    settlement: SettlementResult
    transition_cashflows: pd.DataFrame
    cashflows: pd.DataFrame


@dataclass(frozen=True)
class ScenarioAlternative:
    alternative_id: str
    name: str
    scenario: Scenario

    def __post_init__(self) -> None:
        if not self.alternative_id.strip() or not self.name.strip():
            raise ValueError("alternative identifier and name must not be blank")


@dataclass(frozen=True)
class AlternativeSet:
    comparison_id: str
    alternatives: tuple[ScenarioAlternative, ...]

    def __post_init__(self) -> None:
        if not self.comparison_id.strip():
            raise ValueError("comparison_id must not be blank")
        if len(self.alternatives) < 2:
            raise ValueError("an alternative set requires at least two scenarios")
        ids = [item.alternative_id for item in self.alternatives]
        if len(ids) != len(set(ids)):
            raise ValueError("alternative identifiers must be unique")
        asset_ids = {item.scenario.asset.asset_id for item in self.alternatives}
        currencies = {item.scenario.currency for item in self.alternatives}
        valuation_dates = {item.scenario.valuation_date for item in self.alternatives}
        if len(asset_ids) != 1:
            raise ValueError("alternatives must describe the same physical asset")
        if len(currencies) != 1 or len(valuation_dates) != 1:
            raise ValueError("alternatives must share currency and valuation date")


def build_transition_cashflows(scenario: Scenario) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for transition in scenario.transitions:
        by_date: dict[object, dict[str, Decimal]] = {}
        for period in build_contract_periods(transition.start_date, transition.end_date):
            monthly = transition.monthly_cost * Decimal(period.day_count) / Decimal(
                period.days_in_month
            )
            values = by_date.setdefault(
                period.end_date,
                {"monthly": Decimal("0"), "fixed": Decimal("0"), "explicit": Decimal("0")},
            )
            values["monthly"] += monthly
        start_values = by_date.setdefault(
            transition.start_date,
            {"monthly": Decimal("0"), "fixed": Decimal("0"), "explicit": Decimal("0")},
        )
        start_values["fixed"] += transition.fixed_cost
        for cost in transition.costs:
            values = by_date.setdefault(
                cost.payment_date,
                {"monthly": Decimal("0"), "fixed": Decimal("0"), "explicit": Decimal("0")},
            )
            values["explicit"] += cost.amount
        for payment_date, values in sorted(by_date.items()):
            total = values["monthly"] + values["fixed"] + values["explicit"]
            if total:
                rows.append({
                    "date": payment_date,
                    "transition_id": transition.transition_id,
                    "description": transition.description,
                    "monthly_cost": values["monthly"],
                    "fixed_cost": values["fixed"],
                    "explicit_cost": values["explicit"],
                    "total_transition_cost": total,
                })
    rows.sort(key=lambda row: (row["date"], row["transition_id"]))
    return pd.DataFrame(rows, columns=TRANSITION_CASHFLOW_COLUMNS)


def build_lifecycle_economics(scenario: Scenario) -> LifecycleEconomicsResult:
    settlement = build_lifecycle_settlement(scenario)
    transitions = build_transition_cashflows(scenario)
    dates = set(settlement.cashflows["date"]) | set(transitions["date"])
    rows: list[dict[str, object]] = []
    for current in sorted(dates):
        base = settlement.cashflows.loc[settlement.cashflows["date"] == current]
        costs = transitions.loc[transitions["date"] == current]
        def total(column: str) -> Decimal:
            return sum(base[column], Decimal("0"))
        transition_cost = sum(costs["total_transition_cost"], Decimal("0"))
        rows.append({
            "date": current,
            "rent_inflow": total("rent_inflow"),
            "maintenance_reserve_inflow": total("maintenance_reserve_inflow"),
            "maintenance_cost": total("maintenance_cost"),
            "redelivery_cash_inflow": total("redelivery_cash_inflow"),
            "reserve_refund_outflow": total("reserve_refund_outflow"),
            "transition_cost": transition_cost,
            "net_owner_cashflow": total("net_owner_cashflow") - transition_cost,
        })
    return LifecycleEconomicsResult(
        settlement, transitions,
        pd.DataFrame(rows, columns=ECONOMIC_CASHFLOW_COLUMNS),
    )
