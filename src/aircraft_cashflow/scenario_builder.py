"""Business-facing lessor scenario builder and nominal forecast payload."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any

import pandas as pd

from .config import build_default_case
from .contracts import build_contract_cashflows
from .dates import add_months_eom, completed_months, is_month_end
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
from .models import ComponentConfig, EventDriver, ReserveBasis
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


def _input_amount(value: object) -> str:
    """Format editable currency assumptions to business-level cent precision."""

    return format(
        Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        ".2f",
    )


def _maintenance_program_input(components: tuple[ComponentConfig, ...]) -> list[dict[str, object]]:
    """Serialize editable technical and default reserve component assumptions."""

    return [
        {
            "code": component.code,
            "name": component.name,
            "event_driver": component.event_driver.value,
            "interval": str(component.interval),
            "base_cost": str(component.base_cost),
            "cost_base_date": component.cost_base_date.isoformat(),
            "annual_cost_escalation": str(component.annual_cost_escalation),
            "reserve_basis": component.reserve_basis.value,
            "base_reserve_rate": str(component.base_reserve_rate),
            "reserve_rate_base_date": component.reserve_rate_base_date.isoformat(),
            "annual_reserve_escalation": str(component.annual_reserve_escalation),
        }
        for component in components
    ]


def _components_from_input(
    payload: dict[str, object], defaults: tuple[ComponentConfig, ...]
) -> tuple[ComponentConfig, ...]:
    """Build the aircraft maintenance program, preserving legacy saved inputs."""

    raw_program = payload.get("maintenance_program")
    if raw_program is None:
        return defaults
    if not isinstance(raw_program, list) or not raw_program:
        raise ValueError("maintenance_program must be a non-empty array")
    components: list[ComponentConfig] = []
    for index, raw in enumerate(raw_program, start=1):
        if not isinstance(raw, dict):
            raise ValueError("each maintenance_program item must be an object")
        code = str(raw.get("code", "")).strip()
        prefix = code or f"maintenance_program[{index}]"
        driver = EventDriver(str(raw.get("event_driver", "")))
        components.append(
            ComponentConfig(
                code=code,
                name=str(raw.get("name", code)),
                event_driver=driver,
                interval=raw.get("interval", "0"),
                base_cost=raw.get("base_cost", "0"),
                cost_base_date=_date(raw.get("cost_base_date"), f"{prefix}.cost_base_date"),
                annual_cost_escalation=raw.get("annual_cost_escalation", "0"),
                reserve_basis=ReserveBasis(str(raw.get("reserve_basis", ""))),
                base_reserve_rate=raw.get("base_reserve_rate", "0"),
                reserve_rate_base_date=_date(
                    raw.get("reserve_rate_base_date"),
                    f"{prefix}.reserve_rate_base_date",
                ),
                annual_reserve_escalation=raw.get(
                    "annual_reserve_escalation", "0"
                ),
                usage_since_event_at_lease_start=(
                    raw.get("usage_since_event_at_lease_start", "0")
                    if driver is not EventDriver.CALENDAR_MONTHS else None
                ),
            )
        )
    return tuple(components)


def _reconstruct_known_state(
    asset: AircraftAsset,
    analysis_date: date,
    active_lease: LeaseContract,
    leases: tuple[LeaseContract, ...],
    regimes: tuple[UtilizationRegime, ...],
    transitions: tuple[TransitionPeriod, ...],
) -> KnownState:
    """Rebuild the active lease's analysis-date state from modeled history.

    This intentionally mirrors the verified workbook method: fixed monthly
    utilization is applied from manufacture, maintenance is assumed to occur at
    theoretical intervals, and each component reserve account is rolled from the
    active lease start through the analysis-date period.
    """

    first_start = min(
        [lease.start_date for lease in leases]
        + [transition.start_date for transition in transitions]
    )
    first_regime = next(
        (regime for regime in regimes if regime.start_date <= first_start <= regime.end_date),
        None,
    )
    if first_regime is None:
        raise ValueError("historical reconstruction requires utilization at model start")

    named_dates = {
        "date of manufacture": asset.date_of_manufacture,
        "first modeled lifecycle date": first_start,
        "analysis date": analysis_date,
    }
    invalid = [name for name, value in named_dates.items() if not is_month_end(value)]
    if invalid:
        raise ValueError(
            "historical reconstruction currently requires month-end dates: "
            + ", ".join(invalid)
        )

    prehistory_months = completed_months(asset.date_of_manufacture, first_start)
    opening_ttsn = first_regime.monthly_fh * prehistory_months
    opening_tcsn = first_regime.monthly_fc * prehistory_months
    opening_usage: dict[str, Decimal] = {}
    opening_last_dates: dict[str, date] = {}
    for component in asset.components:
        if component.event_driver is EventDriver.FLIGHT_HOURS:
            opening_usage[component.code] = opening_ttsn % component.interval
        elif component.event_driver is EventDriver.FLIGHT_CYCLES:
            opening_usage[component.code] = opening_tcsn % component.interval
        else:
            elapsed = completed_months(asset.date_of_manufacture, first_start)
            count = elapsed // int(component.interval)
            if count:
                opening_last_dates[component.code] = add_months_eom(
                    asset.date_of_manufacture, count * int(component.interval)
                )

    opening_state = KnownState(
        first_start,
        opening_ttsn,
        opening_tcsn,
        component_usage_since_event=opening_usage,
        component_last_event_dates=opening_last_dates,
    )
    history_scenario = Scenario(
        "opening-state-reconstruction",
        "Opening-state reconstruction",
        asset,
        first_start,
        CutoffPosition.AFTER_EXPIRY_SETTLEMENT,
        first_start,
        analysis_date,
        leases,
        regimes,
        transitions,
        known_state=opening_state,
    )
    utilization = build_lifecycle_utilization(history_scenario)
    usage_row = utilization.iloc[-1]
    settlement = build_lifecycle_economics(history_scenario).settlement
    ledger = settlement.reserve_ledger.loc[
        (settlement.reserve_ledger["lease_id"] == active_lease.contract_id)
        & (settlement.reserve_ledger["date"] <= analysis_date)
    ]

    final_ttsn = Decimal(str(usage_row["ttsn"]))
    final_tcsn = Decimal(str(usage_row["tcsn"]))
    component_usage: dict[str, Decimal] = {}
    last_dates = dict(opening_last_dates)
    for component in asset.components:
        if component.event_driver is EventDriver.FLIGHT_HOURS:
            component_usage[component.code] = final_ttsn % component.interval
        elif component.event_driver is EventDriver.FLIGHT_CYCLES:
            component_usage[component.code] = final_tcsn % component.interval
        component_events = settlement.events.loc[
            (settlement.events["component_code"] == component.code)
            & (settlement.events["date"] <= analysis_date)
        ]
        if not component_events.empty:
            last_dates[component.code] = component_events.iloc[-1]["date"]

    reserve_balances: dict[str, Decimal] = {}
    for component in asset.components:
        account_rows = ledger.loc[ledger["component_code"] == component.code]
        reserve_balances[f"{active_lease.contract_id}:{component.code}"] = (
            Decimal(str(account_rows.iloc[-1]["closing_balance"]))
            if not account_rows.empty else Decimal("0")
        )

    return KnownState(
        analysis_date,
        final_ttsn,
        final_tcsn,
        component_usage_since_event=component_usage,
        reserve_account_balances=reserve_balances,
        component_last_event_dates=last_dates,
    )


def default_scenario_input() -> dict[str, object]:
    """Return one editable, complete lifecycle path for the local dashboard."""

    case = build_default_case()
    state = _known_state()
    return {
        "scenario_id": "base-plan",
        "name": "Current lease and follow-on plan",
        "analysis_date": case.analysis_date.isoformat(),
        "forecast_end_date": "2032-01-31",
        "cutoff_position": CutoffPosition.AFTER_EXPIRY_SETTLEMENT.value,
        "currency": "USD",
        "aircraft": {
            "asset_id": "aircraft-1",
            "aircraft_type": case.aircraft_type,
            "date_of_manufacture": case.date_of_manufacture.isoformat(),
        },
        "maintenance_program": _maintenance_program_input(case.components),
        "known_state": {
            "basis": "reconstructed",
            "ttsn": str(state.ttsn),
            "tcsn": str(state.tcsn),
            "component_usage_since_event": _serialize(
                state.component_usage_since_event
            ),
            "component_last_event_dates": _serialize(
                state.component_last_event_dates
            ),
            "reserve_balances": {
                code: _input_amount(state.reserve_account_balances[f"lease-1:{code}"])
                for code in case.components_by_code
            } if hasattr(case, "components_by_code") else {
                component.code: _input_amount(
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
                "monthly_fh": str(case.default_monthly_fh),
                "monthly_fc": str(case.default_monthly_fc),
                "reserve_rate_multiplier": "1", "redelivery_minimum_ratio": "0.35",
                "closeout_rule": ReserveCloseoutRule.RETAIN_BY_LESSOR.value,
            },
            {
                "type": "lease", "id": "follow-on-1",
                "lessee": "Follow-on Airline", "start_date": "2029-07-01",
                "end_date": "2032-01-31",
                "monthly_fh": "250", "monthly_fc": "95",
                "reserve_rate_multiplier": "1.05",
                "redelivery_minimum_ratio": "0.50",
                "closeout_rule": ReserveCloseoutRule.RETAIN_BY_LESSOR.value,
            },
        ],
    }


def scenario_from_input(payload: dict[str, object]) -> Scenario:
    """Validate and convert a business-facing scenario payload."""

    case = build_default_case()
    components = _components_from_input(payload, case.components)
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
            explicit_escalations = raw.get("reserve_escalations", {})
            if not isinstance(explicit_escalations, dict):
                raise ValueError(f"{segment_id}.reserve_escalations must be an object")
            unknown_escalations = set(explicit_escalations) - component_codes
            if unknown_escalations:
                raise ValueError(
                    f"unknown reserve escalation components: {sorted(unknown_escalations)}"
                )
            rate_base_date_input = raw.get("reserve_rate_base_date")
            closeout = ReserveCloseoutRule(
                str(raw.get("closeout_rule", ReserveCloseoutRule.RETAIN_BY_LESSOR.value))
            )
            accounts = tuple(
                ReserveAccountRule(
                    f"{segment_id}:{component.code}", component.code,
                    component.reserve_basis,
                    explicit_rates.get(component.code, component.base_reserve_rate * multiplier),
                    _date(
                        rate_base_date_input
                        if rate_base_date_input is not None
                        else component.reserve_rate_base_date,
                        f"{segment_id}.{component.code}.reserve_rate_base_date",
                    ),
                    explicit_escalations.get(
                        component.code,
                        raw.get("reserve_escalation", component.annual_reserve_escalation),
                    ),
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
                    accounts, monthly_rent=Decimal("0"),
                    redelivery_conditions=conditions,
                )
            )
        elif segment_type == "transition":
            transitions.append(
                TransitionPeriod(
                    segment_id, start, end,
                    str(raw.get("description", "Transition")),
                    Decimal("0"), Decimal("0"),
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
    state_basis = str(state_input.get("basis", "actual"))
    if state_basis not in {"actual", "reconstructed"}:
        raise ValueError("known_state.basis must be actual or reconstructed")
    if state_basis == "reconstructed":
        if active_lease is None:
            raise ValueError(
                "historical reconstruction requires a lease active at the analysis date"
            )
        active_regimes = [
            regime for regime in regimes
            if regime.segment_id == active_lease.contract_id
            and regime.start_date <= analysis_date <= regime.end_date
        ]
        if len(active_regimes) != 1:
            raise ValueError(
                "historical reconstruction requires one utilization regime at the analysis date"
            )
        known_state = _reconstruct_known_state(
            asset,
            analysis_date,
            active_lease,
            tuple(leases),
            tuple(regimes),
            tuple(transitions),
        )
    else:
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
    ledger = economics.settlement.reserve_ledger.copy()
    ledger["balance_before_closeout"] = (
        ledger["closing_balance"]
        + ledger["retained_by_lessor"]
        + ledger["refund_to_lessee"]
        + ledger["redelivery_offset"]
    )
    cash = economics.cashflows
    reserve_cashflow_rows: list[dict[str, object]] = []
    for current_date in sorted(set(ledger["date"])):
        dated = ledger.loc[ledger["date"] == current_date]
        inflow = sum(dated["reserve_inflow"], Decimal("0"))
        reimbursement = sum(dated["reserve_reimbursement"], Decimal("0"))
        refund = sum(dated["refund_to_lessee"], Decimal("0"))
        reserve_cashflow_rows.append({
            "date": current_date,
            "reserve_inflow": inflow,
            "event_cost": sum(dated["event_cost"], Decimal("0")),
            "reserve_outflow": reimbursement,
            "unfunded_amount": sum(dated["unfunded_amount"], Decimal("0")),
            "refund_to_lessee": refund,
            "retained_by_lessor": sum(dated["retained_by_lessor"], Decimal("0")),
            "balance_before_closeout": sum(
                dated["balance_before_closeout"], Decimal("0")
            ),
            "closing_balance": sum(dated["closing_balance"], Decimal("0")),
            "net_reserve_cash_movement": inflow - reimbursement - refund,
        })
    scenario_output = scenario.to_dict()
    for lease in scenario_output["leases"]:
        lease.pop("monthly_rent", None)
        lease.pop("rent_base_date", None)
        lease.pop("annual_rent_escalation", None)
    contract_periods = contracts.periods.drop(
        columns=["rent_rate", "rent_inflow", "total_contract_inflow"],
        errors="ignore",
    )
    total_event_cost = sum(events["event_cost"], Decimal("0"))
    total_reserve_reimbursement = sum(
        events["reserve_reimbursement"], Decimal("0")
    )
    summary = {
        "forecast_start": scenario.analysis_date,
        "forecast_end": scenario.comparison_horizon,
        "forecast_months": len(contract_periods),
        "lease_count": len(scenario.leases),
        "transition_count": len(scenario.transitions),
        "total_flight_hours": sum(contract_periods["flight_hours"], Decimal("0")),
        "total_flight_cycles": sum(contract_periods["flight_cycles"], Decimal("0")),
        "total_reserve_collections": sum(cash["maintenance_reserve_inflow"], Decimal("0")),
        "total_event_cost": total_event_cost,
        "total_reserve_reimbursement": total_reserve_reimbursement,
        "total_lessee_unfunded": sum(events["lessee_unfunded_amount"], Decimal("0")),
        "largest_lessee_top_up": (
            max(events["lessee_unfunded_amount"], default=Decimal("0"))
        ),
        "reserve_funding_coverage": (
            total_reserve_reimbursement / total_event_cost
            if total_event_cost else Decimal("0")
        ),
        "total_lessor_direct_maintenance": sum(events["lessor_direct_maintenance_amount"], Decimal("0")),
        "total_redelivery_cash": sum(cash["redelivery_cash_inflow"], Decimal("0")),
        "total_reserve_refunds": sum(cash["reserve_refund_outflow"], Decimal("0")),
        "net_reserve_cash_movement": sum(
            (row["net_reserve_cash_movement"] for row in reserve_cashflow_rows),
            Decimal("0"),
        ),
        "maintenance_event_count": len(events),
        "retained_reserve": sum(ledger["retained_by_lessor"], Decimal("0")),
    }
    state_basis = str(
        input_payload.get("known_state", {}).get("basis", "actual")
        if isinstance(input_payload.get("known_state", {}), dict) else "actual"
    )
    active_lease = next(
        (
            lease for lease in scenario.leases
            if lease.start_date <= scenario.analysis_date <= lease.end_date
        ),
        None,
    )
    known = scenario.known_state
    resolved_known_state = {
        "basis": state_basis,
        "as_of_date": known.as_of_date if known else scenario.analysis_date,
        "ttsn": known.ttsn if known else Decimal("0"),
        "tcsn": known.tcsn if known else Decimal("0"),
        "component_usage_since_event": (
            known.component_usage_since_event if known else {}
        ),
        "component_last_event_dates": (
            known.component_last_event_dates if known else {}
        ),
        "reserve_balances": {
            code: known.reserve_account_balances.get(
                f"{active_lease.contract_id}:{code}", Decimal("0")
            )
            for code in scenario.asset.component_codes
        } if known and active_lease else {},
        "active_lease_id": active_lease.contract_id if active_lease else None,
        "technical_state_source": (
            "theoretical_interval_reconstruction"
            if state_basis == "reconstructed" else "actual_user_input"
        ),
        "reserve_balance_source": (
            "historical_lease_rollforward"
            if state_basis == "reconstructed" else "actual_statement_or_manual_input"
        ),
    }
    return _serialize({
        "run": {
            "calculated_at": calculated_at or datetime.now(timezone.utc),
            "model_version": "2.1.0",
            "calculation_engine": "deterministic",
            "perspective": "lessor",
            "valuation_basis": "maintenance_reserve_cashflow",
        },
        "scenario_input": input_payload,
        "scenario": scenario_output,
        "resolved_known_state": resolved_known_state,
        "summary": summary,
        "utilization": _records(utilization),
        "contract_periods": _records(contract_periods),
        "reserve_accounts": _records(contracts.reserve_accounts),
        "events": _records(events),
        "component_states": _records(economics.settlement.component_states),
        "redelivery": _records(economics.settlement.redelivery),
        "reserve_ledger": _records(ledger),
        "reserve_cashflows": _records(
            pd.DataFrame(reserve_cashflow_rows)
        ),
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
        "comparison_basis": "maintenance_reserve_funding_and_technical_exposure",
        "scenario_count": len(results),
        "summaries": [
            {"scenario_id": result["scenario"]["scenario_id"],
             "scenario_name": result["scenario"]["name"], **result["summary"]}
            for result in results
        ],
    }
