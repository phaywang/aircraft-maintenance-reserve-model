"""Illustrative V2 follow-on lease alternatives for the comparison dashboard."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from .balances import build_full_reserve_balances, closing_balance_column
from .config import build_default_case
from .lifecycle import (
    CutoffPosition, KnownState, LeaseContract, RedeliveryConditionRule,
    ReserveAccountRule, Scenario, TerminalValue, TerminalValueBasis,
    TransitionCost, TransitionPeriod, UtilizationRegime, migrate_v1_case,
)
from .transitions import AlternativeSet, ScenarioAlternative
from .utilization import build_full_utilization


V2_COMMON_HORIZON = date(2033, 12, 31)
V2_DEMO_INPUTS = {
    "30-month": {
        "follow_end": "2032-01-31", "monthly_rent": "335000",
        "monthly_fh": "250", "monthly_fc": "95",
    },
    "42-month": {
        "follow_end": "2033-01-31", "monthly_rent": "315000",
        "monthly_fh": "220", "monthly_fc": "82",
    },
}


def _known_state() -> KnownState:
    case = build_default_case()
    utilization = build_full_utilization(case)
    usage = utilization.loc[utilization["date"] == case.analysis_date].iloc[0]
    balances = build_full_reserve_balances(case)
    balance = balances.loc[balances["date"] == case.analysis_date].iloc[0]
    component_usage: dict[str, Decimal] = {}
    for component in case.components:
        if component.event_driver.value == "flight_hours":
            component_usage[component.code] = Decimal(str(usage["ttsn"])) % component.interval
        elif component.event_driver.value == "flight_cycles":
            component_usage[component.code] = Decimal(str(usage["tcsn"])) % component.interval
    return KnownState(
        case.analysis_date,
        usage["ttsn"],
        usage["tcsn"],
        component_usage_since_event=component_usage,
        reserve_account_balances={
            f"lease-1:{component.code}": balance[closing_balance_column(component.code)]
            for component in case.components
        },
        component_last_event_dates={"6Y": date(2023, 6, 30)},
    )


def _accounts(prefix: str, multiplier: Decimal = Decimal("1")) -> tuple[ReserveAccountRule, ...]:
    case = build_default_case()
    return tuple(
        ReserveAccountRule(
            f"{prefix}:{component.code}", component.code, component.reserve_basis,
            component.base_reserve_rate * multiplier,
            component.reserve_rate_base_date,
            component.annual_reserve_escalation,
        )
        for component in case.components
    )


def _scenario(
    scenario_id: str,
    name: str,
    follow_end: date,
    follow_rent: Decimal,
    follow_fh: Decimal,
    follow_fc: Decimal,
) -> Scenario:
    case = build_default_case()
    asset = migrate_v1_case(case).asset
    existing = LeaseContract(
        "lease-1", case.lessee, case.lease_start_date, case.lease_expiry_date,
        _accounts("lease-1"), monthly_rent=Decimal("300000"),
        redelivery_conditions=tuple(
            RedeliveryConditionRule(component.code, Decimal("0.35"))
            for component in case.components
        ),
    )
    preparation = TransitionPeriod(
        "preparation", date(2029, 7, 1), date(2029, 7, 31),
        "Remarketing and delivery preparation", monthly_cost=Decimal("85000"),
        fixed_cost=Decimal("250000"),
        costs=(TransitionCost("ferry", date(2029, 7, 15), Decimal("120000"), "ferry"),),
    )
    follow = LeaseContract(
        "follow-on", "Follow-on Airline", date(2029, 8, 1), follow_end,
        _accounts("follow-on", Decimal("1.05")), monthly_rent=follow_rent,
        redelivery_conditions=tuple(
            RedeliveryConditionRule(component.code, Decimal("0.50"))
            for component in case.components
        ),
    )
    holding = TransitionPeriod(
        "terminal-holding", follow_end + timedelta(days=1),
        V2_COMMON_HORIZON, "Post-lease holding", monthly_cost=Decimal("45000"),
    )
    regimes = (
        UtilizationRegime(
            "existing-use", "lease-1", existing.start_date, existing.end_date,
            case.default_monthly_fh, case.default_monthly_fc,
        ),
        UtilizationRegime("preparation-ground", "preparation", preparation.start_date, preparation.end_date, 0, 0),
        UtilizationRegime("follow-use", "follow-on", follow.start_date, follow.end_date, follow_fh, follow_fc),
        UtilizationRegime("holding-ground", "terminal-holding", holding.start_date, holding.end_date, 0, 0),
    )
    return Scenario(
        scenario_id, name, asset, case.analysis_date,
        CutoffPosition.AFTER_EXPIRY_SETTLEMENT, case.analysis_date,
        V2_COMMON_HORIZON, (existing, follow), regimes,
        (preparation, holding),
        TerminalValue(V2_COMMON_HORIZON, Decimal("28500000"), TerminalValueBasis.APPRAISAL, Decimal("250000")),
        _known_state(),
    )


def build_v2_demo_alternatives(
    inputs: dict[str, dict[str, object]] | None = None,
) -> AlternativeSet:
    """Return two arbitrary-duration follow-on alternatives on one horizon."""

    values = {
        alternative_id: {**defaults, **((inputs or {}).get(alternative_id, {}))}
        for alternative_id, defaults in V2_DEMO_INPUTS.items()
    }
    def scenario(alternative_id: str, name: str) -> Scenario:
        item = values[alternative_id]
        follow_end = (
            date.fromisoformat(str(item["follow_end"]))
            if not isinstance(item["follow_end"], date) else item["follow_end"]
        )
        if follow_end >= V2_COMMON_HORIZON:
            raise ValueError("follow-on lease must end before the common horizon")
        return _scenario(
            alternative_id, name, follow_end, Decimal(str(item["monthly_rent"])),
            Decimal(str(item["monthly_fh"])), Decimal(str(item["monthly_fc"])),
        )
    return AlternativeSet(
        "follow-on-lease-comparison",
        (
            ScenarioAlternative(
                "30-month", "30-month higher-utilization lease",
                scenario("30-month", "30-month alternative"),
            ),
            ScenarioAlternative(
                "42-month", "42-month lower-utilization lease",
                scenario("42-month", "42-month alternative"),
            ),
        ),
    )
