"""V2.6 scenario-comparison dashboard payload."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

import pandas as pd

from .contracts import build_contract_cashflows
from .analysis import build_decision_analysis, build_llm_explanation_payload
from .lifecycle_utilization import build_lifecycle_utilization
from .transitions import build_lifecycle_economics
from .v2_demo import V2_COMMON_HORIZON, V2_DEMO_INPUTS, build_v2_demo_alternatives
from .valuation import compare_alternatives


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
    return [_serialize(row) for row in frame.to_dict("records")]


def build_v2_dashboard_payload(
    annual_discount_rate: Decimal | int | float | str = Decimal("0.09"),
    baseline_id: str = "30-month",
    alternative_inputs: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    alternatives = build_v2_demo_alternatives(alternative_inputs)
    valuation = compare_alternatives(
        alternatives, annual_discount_rate, baseline_id, V2_COMMON_HORIZON
    )
    analysis = build_decision_analysis(alternatives, valuation)
    explanation = build_llm_explanation_payload(
        alternatives, valuation, analysis
    )
    detail: dict[str, object] = {}
    for alternative in alternatives.alternatives:
        scenario = alternative.scenario
        economics = build_lifecycle_economics(scenario)
        contracts = build_contract_cashflows(scenario)
        detail[alternative.alternative_id] = {
            "name": alternative.name,
            "scenario": scenario.to_dict(),
            "utilization": _records(build_lifecycle_utilization(scenario)),
            "contract_periods": _records(contracts.periods),
            "reserve_accounts": _records(contracts.reserve_accounts),
            "events": _records(economics.settlement.events),
            "component_states": _records(economics.settlement.component_states),
            "redelivery": _records(economics.settlement.redelivery),
            "reserve_ledger": _records(economics.settlement.reserve_ledger),
            "transition_cashflows": _records(economics.transition_cashflows),
            "cashflows": _records(economics.cashflows),
        }
    return _serialize({
        "run": {
            "calculated_at": datetime.now(timezone.utc),
            "model_version": "2.0.0a0",
            "calculation_engine": "deterministic",
        },
        "comparison": {
            "comparison_id": alternatives.comparison_id,
            "baseline_id": baseline_id,
            "annual_discount_rate": Decimal(str(annual_discount_rate)),
            "common_horizon": V2_COMMON_HORIZON,
        },
        "editable_inputs": alternative_inputs or V2_DEMO_INPUTS,
        "valuation_summary": _records(valuation.summary),
        "discounted_cashflows": _records(valuation.discounted_cashflows),
        "decision_analysis": analysis.to_dict(),
        "llm_explanation_payload": explanation,
        "alternatives": detail,
    })
