"""V2.3 physical maintenance events, reserve reimbursement and close-out."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING

import pandas as pd

from .contracts import build_contract_cashflows, escalated_amount
from .lifecycle import (
    CutoffPosition,
    LeaseContract,
    ReserveCloseoutRule,
    Scenario,
    lifecycle_segments,
)
from .lifecycle_utilization import build_lifecycle_utilization
from .models import ComponentConfig, EventDriver


MAINTENANCE_EVENT_COLUMNS = (
    "date", "event_id", "component_code", "component_name", "driver",
    "interval", "segment_id", "segment_type", "lease_id", "account_id",
    "event_cost", "available_reserve", "reserve_reimbursement", "unfunded_amount",
    "lessee_unfunded_amount", "lessor_direct_maintenance_amount",
)
COMPONENT_STATE_COLUMNS = (
    "date", "lease_id", "component_code", "driver", "interval",
    "usage_since_event", "remaining_units", "remaining_ratio",
    "last_event_date", "next_event_date",
)
REDELIVERY_SETTLEMENT_COLUMNS = (
    "date", "lease_id", "lessee", "component_code",
    "required_remaining_ratio", "actual_remaining_ratio", "shortfall_ratio",
    "reference_event_cost", "gross_compensation", "reserve_offset",
    "net_cash_compensation",
)
RESERVE_LEDGER_COLUMNS = (
    "date", "period", "lease_id", "account_id", "component_code",
    "is_expiry_period", "opening_balance", "reserve_inflow", "available_balance",
    "event_cost", "reserve_reimbursement", "unfunded_amount", "redelivery_offset",
    "refund_to_lessee", "retained_by_lessor", "closing_balance", "account_closed",
)
LIFECYCLE_CASHFLOW_COLUMNS = (
    "date", "rent_inflow", "maintenance_reserve_inflow", "maintenance_event_cost",
    "reserve_reimbursement_outflow", "lessor_direct_maintenance_outflow",
    "maintenance_cost",
    "redelivery_cash_inflow", "reserve_refund_outflow", "net_owner_cashflow",
)


@dataclass(frozen=True)
class SettlementResult:
    events: pd.DataFrame
    component_states: pd.DataFrame
    redelivery: pd.DataFrame
    reserve_ledger: pd.DataFrame
    cashflows: pd.DataFrame


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, zero_month = divmod(month_index, 12)
    month = zero_month + 1
    target_last = calendar.monthrange(year, month)[1]
    source_last = calendar.monthrange(value.year, value.month)[1]
    day = target_last if value.day == source_last else min(value.day, target_last)
    return date(year, month, day)


def _segment_for_date(scenario: Scenario, event_date: date) -> object:
    return next(
        segment for segment in lifecycle_segments(scenario)
        if segment.start_date <= event_date <= segment.end_date
    )


def _segment_values(segment: object) -> tuple[str, str, str | None]:
    if isinstance(segment, LeaseContract):
        return segment.contract_id, "lease", segment.contract_id
    return segment.transition_id, "transition", None  # type: ignore[union-attr]


def _account_id(scenario: Scenario, lease_id: str | None, code: str) -> str | None:
    if lease_id is None:
        return None
    lease = next(item for item in scenario.leases if item.contract_id == lease_id)
    rule = next(
        (item for item in lease.reserve_accounts if item.component_code == code), None
    )
    return rule.account_id if rule else None


def _new_event(
    scenario: Scenario, component: ComponentConfig, event_date: date, number: int
) -> dict[str, object]:
    segment_id, segment_type, lease_id = _segment_values(
        _segment_for_date(scenario, event_date)
    )
    return {
        "date": event_date,
        "event_id": f"{component.code}-{number}",
        "component_code": component.code,
        "component_name": component.name,
        "driver": component.event_driver.value,
        "interval": component.interval,
        "segment_id": segment_id,
        "segment_type": segment_type,
        "lease_id": lease_id,
        "account_id": _account_id(scenario, lease_id, component.code),
        "event_cost": escalated_amount(
            component.base_cost, component.annual_cost_escalation,
            component.cost_base_date, event_date,
        ),
        "available_reserve": Decimal("0"),
        "reserve_reimbursement": Decimal("0"),
        "unfunded_amount": Decimal("0"),
        "lessee_unfunded_amount": Decimal("0"),
        "lessor_direct_maintenance_amount": Decimal("0"),
    }


def _calendar_events(
    scenario: Scenario, component: ComponentConfig, simulation_start: date
) -> list[dict[str, object]]:
    if component.interval != component.interval.to_integral_value():
        raise ValueError(f"calendar interval for {component.code} must be whole months")
    known = scenario.known_state
    anchor = (
        known.component_last_event_dates.get(component.code) if known else None
    ) or component.last_event_date or scenario.asset.date_of_manufacture
    interval = int(component.interval)
    next_event = _add_months(anchor, interval)
    while next_event < simulation_start:
        next_event = _add_months(next_event, interval)
    rows: list[dict[str, object]] = []
    while next_event <= scenario.comparison_horizon:
        rows.append(_new_event(scenario, component, next_event, len(rows) + 1))
        next_event = _add_months(next_event, interval)
    return rows


def _usage_events(
    scenario: Scenario, component: ComponentConfig, utilization: pd.DataFrame
) -> list[dict[str, object]]:
    known = scenario.known_state
    running = (
        known.component_usage_since_event.get(component.code, Decimal("0"))
        if known else component.usage_since_event_at_lease_start or Decimal("0")
    )
    usage_column = (
        "flight_hours" if component.event_driver is EventDriver.FLIGHT_HOURS
        else "flight_cycles"
    )
    rows: list[dict[str, object]] = []
    for usage_row in utilization.itertuples(index=False):
        if usage_row.segment_type == "anchor":
            continue
        increment = Decimal(str(getattr(usage_row, usage_column)))
        unallocated = increment
        consumed = Decimal("0")
        while increment and running + unallocated >= component.interval:
            needed = component.interval - running
            consumed += needed
            fraction = consumed / increment
            offset = int(
                (fraction * Decimal(usage_row.day_count)).to_integral_value(
                    rounding=ROUND_CEILING
                )
            ) - 1
            event_date = min(
                usage_row.start_date + timedelta(days=max(offset, 0)), usage_row.date
            )
            rows.append(_new_event(scenario, component, event_date, len(rows) + 1))
            unallocated -= needed
            running = Decimal("0")
        running += unallocated
    return rows


def build_lifecycle_maintenance_events(scenario: Scenario) -> pd.DataFrame:
    """Generate events from physical component state, independent of contracts."""

    utilization = build_lifecycle_utilization(scenario)
    simulation_start = (
        scenario.known_state.as_of_date + timedelta(days=1)
        if scenario.known_state else min(s.start_date for s in lifecycle_segments(scenario))
    )
    rows: list[dict[str, object]] = []
    for component in scenario.asset.components:
        rows.extend(
            _calendar_events(scenario, component, simulation_start)
            if component.event_driver is EventDriver.CALENDAR_MONTHS
            else _usage_events(scenario, component, utilization)
        )
    rows.sort(key=lambda row: (row["date"], row["component_code"]))
    return pd.DataFrame(rows, columns=MAINTENANCE_EVENT_COLUMNS)


def _component_state(
    scenario: Scenario,
    component: ComponentConfig,
    state_date: date,
    utilization: pd.DataFrame,
    events: pd.DataFrame,
) -> dict[str, object]:
    known = scenario.known_state
    component_events = events.loc[
        (events["component_code"] == component.code) & (events["date"] <= state_date)
    ]
    if component.event_driver is EventDriver.CALENDAR_MONTHS:
        anchor = (
            known.component_last_event_dates.get(component.code) if known else None
        ) or component.last_event_date or scenario.asset.date_of_manufacture
        last_event = component_events.iloc[-1]["date"] if not component_events.empty else anchor
        next_event = _add_months(last_event, int(component.interval))
        ratio = Decimal(max((next_event - state_date).days, 0)) / Decimal(
            (next_event - last_event).days
        )
        ratio = min(max(ratio, Decimal("0")), Decimal("1"))
        remaining = component.interval * ratio
        used = component.interval - remaining
    else:
        initial = (
            known.component_usage_since_event.get(component.code, Decimal("0"))
            if known else component.usage_since_event_at_lease_start or Decimal("0")
        )
        column = (
            "flight_hours" if component.event_driver is EventDriver.FLIGHT_HOURS
            else "flight_cycles"
        )
        relevant = utilization.loc[
            (utilization["segment_type"] != "anchor") & (utilization["date"] <= state_date),
            column,
        ]
        used = initial + sum(relevant, Decimal("0")) - component.interval * len(component_events)
        remaining = component.interval - used
        ratio = remaining / component.interval
        last_event = (
            component_events.iloc[-1]["date"] if not component_events.empty
            else (known.component_last_event_dates.get(component.code) if known else component.last_event_date)
        )
        next_event = None
    return {
        "driver": component.event_driver.value,
        "interval": component.interval,
        "usage_since_event": used,
        "remaining_units": remaining,
        "remaining_ratio": ratio,
        "last_event_date": last_event,
        "next_event_date": next_event,
    }


def _settlement_leases(scenario: Scenario) -> list[LeaseContract]:
    if scenario.known_state is None:
        return sorted(scenario.leases, key=lambda item: item.end_date)
    cutoff = scenario.known_state.as_of_date
    return sorted(
        [lease for lease in scenario.leases if lease.end_date > cutoff or (
            lease.end_date == scenario.analysis_date
            and scenario.cutoff_position is CutoffPosition.BEFORE_EXPIRY_SETTLEMENT
        )],
        key=lambda item: item.end_date,
    )


def _states_and_redelivery(
    scenario: Scenario, utilization: pd.DataFrame, events: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    state_rows: list[dict[str, object]] = []
    redelivery_rows: list[dict[str, object]] = []
    components = {item.code: item for item in scenario.asset.components}
    for lease in _settlement_leases(scenario):
        states: dict[str, dict[str, object]] = {}
        for component in scenario.asset.components:
            state = _component_state(scenario, component, lease.end_date, utilization, events)
            states[component.code] = state
            state_rows.append({
                "date": lease.end_date, "lease_id": lease.contract_id,
                "component_code": component.code, **state,
            })
        for condition in lease.redelivery_conditions:
            component = components[condition.component_code]
            actual = Decimal(str(states[component.code]["remaining_ratio"]))
            shortfall = max(condition.minimum_remaining_ratio - actual, Decimal("0"))
            reference_cost = escalated_amount(
                component.base_cost, component.annual_cost_escalation,
                component.cost_base_date, lease.end_date,
            )
            gross = reference_cost * shortfall
            redelivery_rows.append({
                "date": lease.end_date, "lease_id": lease.contract_id,
                "lessee": lease.lessee, "component_code": component.code,
                "required_remaining_ratio": condition.minimum_remaining_ratio,
                "actual_remaining_ratio": actual, "shortfall_ratio": shortfall,
                "reference_event_cost": reference_cost, "gross_compensation": gross,
                "reserve_offset": Decimal("0"), "net_cash_compensation": gross,
            })
    return (
        pd.DataFrame(state_rows, columns=COMPONENT_STATE_COLUMNS),
        pd.DataFrame(redelivery_rows, columns=REDELIVERY_SETTLEMENT_COLUMNS),
    )


def _cashflow_table(
    contract: pd.DataFrame, events: pd.DataFrame, redelivery: pd.DataFrame,
    ledger: pd.DataFrame,
) -> pd.DataFrame:
    dates = set(contract["date"]) | set(events["date"]) | set(redelivery["date"])
    rows: list[dict[str, object]] = []
    for current in sorted(dates):
        c = contract.loc[contract["date"] == current]
        e = events.loc[events["date"] == current]
        r = redelivery.loc[redelivery["date"] == current]
        l = ledger.loc[ledger["date"] == current]
        rent = sum(c["rent_inflow"], Decimal("0"))
        reserves = sum(c["maintenance_reserve_inflow"], Decimal("0"))
        event_cost = sum(e["event_cost"], Decimal("0"))
        reimbursement = sum(e["reserve_reimbursement"], Decimal("0"))
        direct_maintenance = sum(
            e["lessor_direct_maintenance_amount"], Decimal("0")
        )
        compensation = sum(r["net_cash_compensation"], Decimal("0"))
        refunds = sum(l["refund_to_lessee"], Decimal("0"))
        rows.append({
            "date": current, "rent_inflow": rent,
            "maintenance_reserve_inflow": reserves,
            "maintenance_event_cost": event_cost,
            "reserve_reimbursement_outflow": reimbursement,
            "lessor_direct_maintenance_outflow": direct_maintenance,
            # Compatibility alias. In lessor reporting, maintenance cash outflow
            # means the contractual reserve reimbursement, not the full event cost.
            "maintenance_cost": reimbursement + direct_maintenance,
            "redelivery_cash_inflow": compensation,
            "reserve_refund_outflow": refunds,
            "net_owner_cashflow": (
                rent + reserves + compensation
                - reimbursement - direct_maintenance - refunds
            ),
        })
    return pd.DataFrame(rows, columns=LIFECYCLE_CASHFLOW_COLUMNS)


def build_lifecycle_settlement(scenario: Scenario) -> SettlementResult:
    """Apply inflow, event, redelivery and account close-out in required order."""

    utilization = build_lifecycle_utilization(scenario)
    contract = build_contract_cashflows(scenario)
    events = build_lifecycle_maintenance_events(scenario)
    states, redelivery = _states_and_redelivery(scenario, utilization, events)
    event_rows = events.to_dict("records")
    redelivery_rows = redelivery.to_dict("records")
    balances = {
        rule.account_id: Decimal("0") for lease in scenario.leases
        for rule in lease.reserve_accounts
    }
    if scenario.known_state:
        balances.update(scenario.known_state.reserve_account_balances)
    ledger_rows: list[dict[str, object]] = []

    for period in contract.periods.sort_values(["date", "lease_id"]).itertuples(index=False):
        lease = next(item for item in scenario.leases if item.contract_id == period.lease_id)
        detail_rows = contract.reserve_accounts.loc[
            contract.reserve_accounts["period"] == period.period
        ]
        for detail in detail_rows.itertuples(index=False):
            rule = next(item for item in lease.reserve_accounts if item.account_id == detail.account_id)
            opening = balances[rule.account_id]
            inflow = Decimal(str(detail.reserve_inflow))
            available = opening + inflow
            event_cost = reimbursement = unfunded = Decimal("0")
            for event in event_rows:
                if event["account_id"] == rule.account_id and period.period_start <= event["date"] <= period.period_end:
                    cost = Decimal(str(event["event_cost"]))
                    paid = min(available, cost)
                    event.update({
                        "available_reserve": available,
                        "reserve_reimbursement": paid,
                        "unfunded_amount": cost - paid,
                        "lessee_unfunded_amount": cost - paid,
                        "lessor_direct_maintenance_amount": Decimal("0"),
                    })
                    available -= paid
                    event_cost += cost
                    reimbursement += paid
                    unfunded += cost - paid
            offset = refund = retained = Decimal("0")
            if period.is_expiry_period:
                condition = next((row for row in redelivery_rows
                    if row["lease_id"] == lease.contract_id
                    and row["component_code"] == rule.component_code), None)
                if rule.closeout_rule is ReserveCloseoutRule.REFUND_TO_LESSEE:
                    refund = available
                elif rule.closeout_rule is ReserveCloseoutRule.OFFSET_REDELIVERY:
                    gross = Decimal(str(condition["gross_compensation"])) if condition else Decimal("0")
                    offset = min(available, gross)
                    refund = available - offset
                    if condition:
                        condition["reserve_offset"] = offset
                        condition["net_cash_compensation"] = gross - offset
                else:
                    retained = available
                closing = Decimal("0")
            else:
                closing = available
            balances[rule.account_id] = closing
            ledger_rows.append({
                "date": period.date, "period": period.period,
                "lease_id": lease.contract_id, "account_id": rule.account_id,
                "component_code": rule.component_code,
                "is_expiry_period": period.is_expiry_period,
                "opening_balance": opening, "reserve_inflow": inflow,
                "available_balance": opening + inflow, "event_cost": event_cost,
                "reserve_reimbursement": reimbursement, "unfunded_amount": unfunded,
                "redelivery_offset": offset, "refund_to_lessee": refund,
                "retained_by_lessor": retained, "closing_balance": closing,
                "account_closed": bool(period.is_expiry_period),
            })
    for event in event_rows:
        if event["segment_type"] == "transition":
            event["unfunded_amount"] = event["event_cost"]
            event["lessee_unfunded_amount"] = Decimal("0")
            event["lessor_direct_maintenance_amount"] = event["event_cost"]
        elif not Decimal(str(event["reserve_reimbursement"])):
            event["unfunded_amount"] = event["event_cost"]
            event["lessee_unfunded_amount"] = event["event_cost"]
    settled_events = pd.DataFrame(event_rows, columns=MAINTENANCE_EVENT_COLUMNS)
    settled_redelivery = pd.DataFrame(redelivery_rows, columns=REDELIVERY_SETTLEMENT_COLUMNS)
    ledger = pd.DataFrame(ledger_rows, columns=RESERVE_LEDGER_COLUMNS)
    cashflows = _cashflow_table(contract.periods, settled_events, settled_redelivery, ledger)
    return SettlementResult(settled_events, states, settled_redelivery, ledger, cashflows)
