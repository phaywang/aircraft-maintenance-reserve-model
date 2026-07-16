"""Business-facing lessor scenario builder and nominal forecast payload."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

import pandas as pd

from .config import build_default_case
from .contracts import build_contract_cashflows
from .lifecycle import (
    AircraftAsset,
    CutoffPosition,
    KnownState,
    LeaseContract,
    RedeliveryConditionRule,
    ReserveAccountRule,
    ReserveCloseoutRule,
    Scenario,
    TransitionPeriod,
    UtilizationRegime,
)
from .lifecycle_utilization import build_lifecycle_utilization
from .transitions import build_lifecycle_economics
from .v2_demo import _known_state


def _date(value: object, field: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date") from exc


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


def default_scenario_input() -> dict[str, object]:
    """Return one editable, complete lifecycle path for the local dashboard."""

    case = build_default_case()
    state = _known_state()
    return {
        "scenario_id": "base-plan",
        "name": "Current lease and follow-on plan",
        "analysis_date": case.analysis_date.isoformat(),
        "forecast_end_date": "2033-12-31",
        "cutoff_position": CutoffPosition.AFTER_EXPIRY_SETTLEMENT.value,
        "currency": "USD",
        "aircraft": {
            "asset_id": "aircraft-1",
            "aircraft_type": case.aircraft_type,
            "date_of_manufacture": case.date_of_manufacture.isoformat(),
        },
        "known_state": {
            "ttsn": str(state.ttsn),
            "tcsn": str(state.tcsn),
            "component_usage_since_event": _serialize(
                state.component_usage_since_event
            ),
            "component_last_event_dates": _serialize(
                state.component_last_event_dates
            ),
            "reserve_balances": {
                code: str(state.reserve_account_balances[f"lease-1:{code}"])
                for code in case.components_by_code
            } if hasattr(case, "components_by_code") else {
                component.code: str(
                    state.reserve_account_balances[f"lease-1:{component.code}"]
                )
                for component in case.components
            },
        },
        "segments": [
            {
                "type": "lease", "id": "lease-1", "lessee": case.lessee,
                "start_date": case.lease_start_date.isoformat(),
                "end_date": case.lease_expiry_date.isoformat(),
                "monthly_rent": "300000", "monthly_fh": str(case.default_monthly_fh),
                "monthly_fc": str(case.default_monthly_fc),
                "reserve_rate_multiplier": "1", "redelivery_minimum_ratio": "0.35",
                "closeout_rule": ReserveCloseoutRule.RETAIN_BY_LESSOR.value,
            },
            {
                "type": "transition", "id": "preparation",
                "description": "Remarketing and delivery preparation",
                "start_date": "2029-07-01", "end_date": "2029-07-31",
                "monthly_fh": "0", "monthly_fc": "0",
                "monthly_cost": "85000", "fixed_cost": "370000",
            },
            {
                "type": "lease", "id": "follow-on-1",
                "lessee": "Follow-on Airline", "start_date": "2029-08-01",
                "end_date": "2032-01-31", "monthly_rent": "335000",
                "monthly_fh": "250", "monthly_fc": "95",
                "reserve_rate_multiplier": "1.05",
                "redelivery_minimum_ratio": "0.50",
                "closeout_rule": ReserveCloseoutRule.RETAIN_BY_LESSOR.value,
            },
            {
                "type": "transition", "id": "terminal-holding",
                "description": "Post-lease holding",
                "start_date": "2032-02-01", "end_date": "2033-12-31",
                "monthly_fh": "0", "monthly_fc": "0",
                "monthly_cost": "45000", "fixed_cost": "0",
            },
        ],
    }


def scenario_from_input(payload: dict[str, object]) -> Scenario:
    """Validate and convert a business-facing scenario payload."""

    case = build_default_case()
    components = case.components
    component_codes = {component.code for component in components}
    analysis_date = _date(payload.get("analysis_date"), "analysis_date")
    forecast_end = _date(payload.get("forecast_end_date"), "forecast_end_date")
    asset_input = payload.get("aircraft", {})
    if not isinstance(asset_input, dict):
        raise ValueError("aircraft must be an object")
    asset = AircraftAsset(
        str(asset_input.get("asset_id", "aircraft-1")),
        str(asset_input.get("aircraft_type", case.aircraft_type)),
        _date(asset_input.get("date_of_manufacture", case.date_of_manufacture), "date_of_manufacture"),
        components,
    )

    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("segments must be a non-empty array")
    leases: list[LeaseContract] = []
    transitions: list[TransitionPeriod] = []
    regimes: list[UtilizationRegime] = []
    for index, raw in enumerate(raw_segments, start=1):
        if not isinstance(raw, dict):
            raise ValueError("each segment must be an object")
        segment_type = str(raw.get("type", ""))
        segment_id = str(raw.get("id", f"segment-{index}"))
        start = _date(raw.get("start_date"), f"{segment_id}.start_date")
        end = _date(raw.get("end_date"), f"{segment_id}.end_date")
        monthly_fh = raw.get("monthly_fh", "0")
        monthly_fc = raw.get("monthly_fc", "0")
        if segment_type == "lease":
            multiplier = Decimal(str(raw.get("reserve_rate_multiplier", "1")))
            explicit_rates = raw.get("reserve_rates", {})
            if not isinstance(explicit_rates, dict):
                raise ValueError(f"{segment_id}.reserve_rates must be an object")
            unknown_rates = set(explicit_rates) - component_codes
            if unknown_rates:
                raise ValueError(f"unknown reserve rate components: {sorted(unknown_rates)}")
            closeout = ReserveCloseoutRule(
                str(raw.get("closeout_rule", ReserveCloseoutRule.RETAIN_BY_LESSOR.value))
            )
            accounts = tuple(
                ReserveAccountRule(
                    f"{segment_id}:{component.code}", component.code,
                    component.reserve_basis,
                    explicit_rates.get(component.code, component.base_reserve_rate * multiplier),
                    component.reserve_rate_base_date,
                    raw.get("reserve_escalation", component.annual_reserve_escalation),
                    closeout,
                )
                for component in components
            )
            redelivery = raw.get("redelivery_conditions")
            if redelivery is not None and not isinstance(redelivery, dict):
                raise ValueError(f"{segment_id}.redelivery_conditions must be an object")
            default_ratio = raw.get("redelivery_minimum_ratio", "0")
            conditions = tuple(
                RedeliveryConditionRule(
                    component.code,
                    redelivery.get(component.code, default_ratio) if isinstance(redelivery, dict) else default_ratio,
                )
                for component in components
            )
            leases.append(
                LeaseContract(
                    segment_id, str(raw.get("lessee", "Future Lessee")), start, end,
                    accounts, monthly_rent=raw.get("monthly_rent", "0"),
                    annual_rent_escalation=raw.get("annual_rent_escalation", "0"),
                    redelivery_conditions=conditions,
                )
            )
        elif segment_type == "transition":
            transitions.append(
                TransitionPeriod(
                    segment_id, start, end,
                    str(raw.get("description", "Transition")),
                    raw.get("monthly_cost", "0"), raw.get("fixed_cost", "0"),
                )
            )
        else:
            raise ValueError("segment type must be lease or transition")
        regimes.append(
            UtilizationRegime(
                f"{segment_id}-utilization", segment_id, start, end,
                monthly_fh, monthly_fc,
            )
        )

    active_lease = next(
        (lease for lease in leases if lease.start_date <= analysis_date <= lease.end_date),
        None,
    )
    state_input = payload.get("known_state", {})
    if not isinstance(state_input, dict):
        raise ValueError("known_state must be an object")
    balances_input = state_input.get("reserve_balances", {})
    if not isinstance(balances_input, dict):
        raise ValueError("known_state.reserve_balances must be an object")
    if active_lease is None and balances_input:
        raise ValueError("reserve balances require a lease active at the analysis date")
    unknown_balances = set(balances_input) - component_codes
    if unknown_balances:
        raise ValueError(f"unknown reserve balance components: {sorted(unknown_balances)}")
    usage = state_input.get("component_usage_since_event", {})
    last_dates = state_input.get("component_last_event_dates", {})
    if not isinstance(usage, dict) or not isinstance(last_dates, dict):
        raise ValueError("known-state component fields must be objects")
    known_state = KnownState(
        analysis_date,
        state_input.get("ttsn", "0"), state_input.get("tcsn", "0"),
        component_usage_since_event=usage,
        reserve_account_balances={
            f"{active_lease.contract_id}:{code}": value
            for code, value in balances_input.items()
        } if active_lease else {},
        component_last_event_dates={
            code: _date(value, f"last event date {code}")
            for code, value in last_dates.items()
        },
    )
    return Scenario(
        str(payload.get("scenario_id", "scenario")),
        str(payload.get("name", "Lifecycle scenario")), asset, analysis_date,
        CutoffPosition(str(payload.get("cutoff_position", CutoffPosition.AFTER_EXPIRY_SETTLEMENT.value))),
        analysis_date, forecast_end, tuple(leases), tuple(regimes),
        tuple(transitions), known_state=known_state,
        currency=str(payload.get("currency", "USD")),
    )


def build_scenario_payload(
    scenario_input: dict[str, object] | None = None,
    calculated_at: datetime | None = None,
) -> dict[str, object]:
    """Run one nominal lessor lifecycle scenario and return auditable tables."""

    input_payload = scenario_input or default_scenario_input()
    scenario = scenario_from_input(input_payload)
    economics = build_lifecycle_economics(scenario)
    contracts = build_contract_cashflows(scenario)
    utilization = build_lifecycle_utilization(scenario)
    events = economics.settlement.events
    ledger = economics.settlement.reserve_ledger
    cash = economics.cashflows
    summary = {
        "forecast_start": scenario.analysis_date,
        "forecast_end": scenario.comparison_horizon,
        "lease_count": len(scenario.leases),
        "transition_count": len(scenario.transitions),
        "total_rent": sum(cash["rent_inflow"], Decimal("0")),
        "total_reserve_collections": sum(cash["maintenance_reserve_inflow"], Decimal("0")),
        "total_event_cost": sum(events["event_cost"], Decimal("0")),
        "total_reserve_reimbursement": sum(events["reserve_reimbursement"], Decimal("0")),
        "total_lessee_unfunded": sum(events["lessee_unfunded_amount"], Decimal("0")),
        "total_lessor_direct_maintenance": sum(events["lessor_direct_maintenance_amount"], Decimal("0")),
        "total_redelivery_cash": sum(cash["redelivery_cash_inflow"], Decimal("0")),
        "total_reserve_refunds": sum(cash["reserve_refund_outflow"], Decimal("0")),
        "total_transition_cost": sum(cash["transition_cost"], Decimal("0")),
        "nominal_net_lessor_cashflow": sum(cash["net_owner_cashflow"], Decimal("0")),
        "maintenance_event_count": len(events),
        "minimum_dated_cashflow": min(cash["net_owner_cashflow"], default=Decimal("0")),
        "retained_reserve": sum(ledger["retained_by_lessor"], Decimal("0")),
    }
    return _serialize({
        "run": {
            "calculated_at": calculated_at or datetime.now(timezone.utc),
            "model_version": "2.1.0",
            "calculation_engine": "deterministic",
            "perspective": "lessor",
            "valuation_basis": "nominal_cashflow",
        },
        "scenario_input": input_payload,
        "scenario": scenario.to_dict(),
        "summary": summary,
        "utilization": _records(utilization),
        "contract_periods": _records(contracts.periods),
        "reserve_accounts": _records(contracts.reserve_accounts),
        "events": _records(events),
        "component_states": _records(economics.settlement.component_states),
        "redelivery": _records(economics.settlement.redelivery),
        "reserve_ledger": _records(ledger),
        "transition_cashflows": _records(economics.transition_cashflows),
        "cashflows": _records(cash),
    })


def compare_scenario_payloads(
    scenario_inputs: list[dict[str, object]],
) -> dict[str, object]:
    """Compare any number of independent nominal scenario forecasts."""

    if len(scenario_inputs) < 2:
        raise ValueError("scenario comparison requires at least two scenarios")
    results = [build_scenario_payload(item) for item in scenario_inputs]
    ids = [str(result["scenario"]["scenario_id"]) for result in results]
    if len(ids) != len(set(ids)):
        raise ValueError("scenario identifiers must be unique for comparison")
    return {
        "comparison_basis": "nominal_lessor_cashflow_and_technical_exposure",
        "scenario_count": len(results),
        "summaries": [
            {"scenario_id": result["scenario"]["scenario_id"],
             "scenario_name": result["scenario"]["name"], **result["summary"]}
            for result in results
        ],
    }

