"""V2.8 one-way sensitivity analysis and recommendation-switch detection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import Enum

import pandas as pd

from .lifecycle import Scenario
from .models import to_decimal
from .transitions import AlternativeSet, ScenarioAlternative
from .valuation import compare_alternatives


class SensitivityVariable(str, Enum):
    DISCOUNT_RATE = "discount_rate"
    RENT = "rent"
    UTILIZATION = "utilization"
    MAINTENANCE_COST = "maintenance_cost"
    TRANSITION_COST = "transition_cost"
    TERMINAL_VALUE = "terminal_value"


@dataclass(frozen=True)
class SensitivitySpec:
    sensitivity_id: str
    label: str
    variable: SensitivityVariable
    low: Decimal | int | float | str
    high: Decimal | int | float | str
    target_alternative_id: str | None = None

    def __post_init__(self) -> None:
        if not self.sensitivity_id.strip() or not self.label.strip():
            raise ValueError("sensitivity identifier and label must not be blank")
        low = to_decimal(self.low, "sensitivity low")
        high = to_decimal(self.high, "sensitivity high")
        if low < 0 or high < 0 or low > high:
            raise ValueError("sensitivity values must be nonnegative and ordered")
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "high", high)


SENSITIVITY_CASE_COLUMNS = (
    "case_id", "sensitivity_id", "label", "variable", "level", "shock_value",
    "target_alternative_id", "recommended_alternative_id", "winner_npv",
    "runner_up_npv", "npv_gap", "recommendation_changed",
)
SENSITIVITY_VALUE_COLUMNS = (
    "case_id", "alternative_id", "npv", "incremental_npv",
)
SENSITIVITY_DRIVER_COLUMNS = (
    "sensitivity_id", "label", "variable", "minimum_npv_gap", "maximum_npv_gap",
    "recommendation_switch_count",
)
UNCERTAINTY_RANGE_COLUMNS = (
    "alternative_id", "base_npv", "minimum_npv", "maximum_npv",
    "downside_from_base", "upside_from_base", "recommendation_count",
    "recommendation_frequency",
)


@dataclass(frozen=True)
class SensitivityResult:
    cases: pd.DataFrame
    alternative_values: pd.DataFrame
    drivers: pd.DataFrame
    uncertainty_ranges: pd.DataFrame
    base_recommendation_id: str


def _scale_scenario(
    scenario: Scenario, variable: SensitivityVariable, value: Decimal
) -> Scenario:
    if variable is SensitivityVariable.RENT:
        return replace(
            scenario,
            leases=tuple(replace(lease, monthly_rent=lease.monthly_rent * value) for lease in scenario.leases),
        )
    if variable is SensitivityVariable.UTILIZATION:
        return replace(
            scenario,
            utilization_regimes=tuple(
                replace(regime, monthly_fh=regime.monthly_fh * value, monthly_fc=regime.monthly_fc * value)
                for regime in scenario.utilization_regimes
            ),
        )
    if variable is SensitivityVariable.MAINTENANCE_COST:
        asset = replace(
            scenario.asset,
            components=tuple(
                replace(component, base_cost=component.base_cost * value)
                for component in scenario.asset.components
            ),
        )
        return replace(scenario, asset=asset)
    if variable is SensitivityVariable.TRANSITION_COST:
        return replace(
            scenario,
            transitions=tuple(
                replace(
                    transition,
                    monthly_cost=transition.monthly_cost * value,
                    fixed_cost=transition.fixed_cost * value,
                    costs=tuple(replace(cost, amount=cost.amount * value) for cost in transition.costs),
                )
                for transition in scenario.transitions
            ),
        )
    if variable is SensitivityVariable.TERMINAL_VALUE:
        if scenario.terminal_value is None:
            raise ValueError("terminal-value sensitivity requires terminal value")
        return replace(
            scenario,
            terminal_value=replace(scenario.terminal_value, amount=scenario.terminal_value.amount * value),
        )
    return scenario


def _shocked_set(
    alternatives: AlternativeSet, spec: SensitivitySpec, value: Decimal
) -> AlternativeSet:
    items = tuple(
        ScenarioAlternative(
            item.alternative_id,
            item.name,
            _scale_scenario(item.scenario, spec.variable, value)
            if spec.target_alternative_id in (None, item.alternative_id)
            else item.scenario,
        )
        for item in alternatives.alternatives
    )
    return AlternativeSet(alternatives.comparison_id, items)


def default_sensitivity_specs() -> tuple[SensitivitySpec, ...]:
    return (
        SensitivitySpec("discount-rate", "Discount rate", SensitivityVariable.DISCOUNT_RATE, "0.06", "0.12"),
        SensitivitySpec("rent-30", "30-month rent", SensitivityVariable.RENT, "0.80", "1.20", "30-month"),
        SensitivitySpec("rent-42", "42-month rent", SensitivityVariable.RENT, "0.80", "1.20", "42-month"),
        SensitivitySpec("utilization-30", "30-month utilization", SensitivityVariable.UTILIZATION, "0.80", "1.20", "30-month"),
        SensitivitySpec("utilization-42", "42-month utilization", SensitivityVariable.UTILIZATION, "0.80", "1.20", "42-month"),
        SensitivitySpec("maintenance-30", "30-month maintenance cost", SensitivityVariable.MAINTENANCE_COST, "0.50", "1.50", "30-month"),
        SensitivitySpec("maintenance-42", "42-month maintenance cost", SensitivityVariable.MAINTENANCE_COST, "0.50", "1.50", "42-month"),
        SensitivitySpec("transition", "Transition cost", SensitivityVariable.TRANSITION_COST, "0.50", "1.50"),
        SensitivitySpec("terminal", "Terminal value", SensitivityVariable.TERMINAL_VALUE, "0.80", "1.20"),
    )


def run_sensitivity_analysis(
    alternatives: AlternativeSet,
    annual_discount_rate: Decimal | int | float | str,
    baseline_id: str,
    common_horizon: date,
    specs: tuple[SensitivitySpec, ...] | None = None,
) -> SensitivityResult:
    rate = to_decimal(annual_discount_rate, "annual_discount_rate")
    base = compare_alternatives(alternatives, rate, baseline_id, common_horizon)
    base_ranked = sorted(base.summary.to_dict("records"), key=lambda row: Decimal(str(row["npv"])), reverse=True)
    base_winner = str(base_ranked[0]["alternative_id"])
    case_rows: list[dict[str, object]] = []
    value_rows: list[dict[str, object]] = []

    def add_case(case_id: str, spec: SensitivitySpec | None, level: str, value: Decimal, valuation: object) -> None:
        rows = sorted(valuation.summary.to_dict("records"), key=lambda row: Decimal(str(row["npv"])), reverse=True)
        winner, runner = rows[0], rows[1]
        case_rows.append({
            "case_id": case_id,
            "sensitivity_id": spec.sensitivity_id if spec else "base",
            "label": spec.label if spec else "Baseline",
            "variable": spec.variable.value if spec else "base",
            "level": level,
            "shock_value": value,
            "target_alternative_id": spec.target_alternative_id if spec else None,
            "recommended_alternative_id": winner["alternative_id"],
            "winner_npv": winner["npv"],
            "runner_up_npv": runner["npv"],
            "npv_gap": Decimal(str(winner["npv"])) - Decimal(str(runner["npv"])),
            "recommendation_changed": winner["alternative_id"] != base_winner,
        })
        value_rows.extend({
            "case_id": case_id, "alternative_id": row["alternative_id"],
            "npv": row["npv"], "incremental_npv": row["incremental_npv"],
        } for row in rows)

    add_case("base", None, "base", rate, base)
    for spec in specs or default_sensitivity_specs():
        for level, value in (("low", spec.low), ("high", spec.high)):
            shocked = alternatives if spec.variable is SensitivityVariable.DISCOUNT_RATE else _shocked_set(alternatives, spec, value)
            shocked_rate = value if spec.variable is SensitivityVariable.DISCOUNT_RATE else rate
            valuation = compare_alternatives(shocked, shocked_rate, baseline_id, common_horizon)
            add_case(f"{spec.sensitivity_id}:{level}", spec, level, value, valuation)
    cases = pd.DataFrame(case_rows, columns=SENSITIVITY_CASE_COLUMNS)
    driver_rows = []
    for spec in specs or default_sensitivity_specs():
        subset = cases.loc[cases["sensitivity_id"] == spec.sensitivity_id]
        driver_rows.append({
            "sensitivity_id": spec.sensitivity_id, "label": spec.label,
            "variable": spec.variable.value,
            "minimum_npv_gap": min(subset["npv_gap"]),
            "maximum_npv_gap": max(subset["npv_gap"]),
            "recommendation_switch_count": int(subset["recommendation_changed"].sum()),
        })
    values = pd.DataFrame(value_rows, columns=SENSITIVITY_VALUE_COLUMNS)
    uncertainty_rows = []
    for alternative_id in sorted(values["alternative_id"].unique()):
        subset = values.loc[values["alternative_id"] == alternative_id]
        base_npv = Decimal(str(subset.loc[subset["case_id"] == "base"].iloc[0]["npv"]))
        minimum = min(subset["npv"])
        maximum = max(subset["npv"])
        recommendation_count = int(
            (cases["recommended_alternative_id"] == alternative_id).sum()
        )
        uncertainty_rows.append({
            "alternative_id": alternative_id,
            "base_npv": base_npv,
            "minimum_npv": minimum,
            "maximum_npv": maximum,
            "downside_from_base": Decimal(str(minimum)) - base_npv,
            "upside_from_base": Decimal(str(maximum)) - base_npv,
            "recommendation_count": recommendation_count,
            "recommendation_frequency": Decimal(recommendation_count) / Decimal(len(cases)),
        })
    return SensitivityResult(
        cases,
        values,
        pd.DataFrame(driver_rows, columns=SENSITIVITY_DRIVER_COLUMNS),
        pd.DataFrame(uncertainty_rows, columns=UNCERTAINTY_RANGE_COLUMNS),
        base_winner,
    )
