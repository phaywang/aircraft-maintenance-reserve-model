"""V2.2 lease rent and maintenance-reserve cash-flow engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from .lifecycle import (
    LeaseContract,
    ProrationConvention,
    ReserveAccountRule,
    Scenario,
    build_contract_periods,
)
from .lifecycle_utilization import build_lifecycle_utilization
from .models import ReserveBasis


RESERVE_ACCOUNT_INFLOW_COLUMNS = (
    "date",
    "period",
    "lease_id",
    "lessee",
    "period_start",
    "period_end",
    "contractual_due_date",
    "is_expiry_period",
    "is_stub",
    "modeled_day_count",
    "days_in_month",
    "fixed_charge_factor",
    "flight_hours",
    "flight_cycles",
    "account_id",
    "component_code",
    "reserve_basis",
    "reserve_rate",
    "reserve_units",
    "reserve_inflow",
)

LEASE_CASHFLOW_COLUMNS = (
    "date",
    "period",
    "lease_id",
    "lessee",
    "period_start",
    "period_end",
    "contractual_due_date",
    "is_expiry_period",
    "is_stub",
    "modeled_day_count",
    "days_in_month",
    "fixed_charge_factor",
    "flight_hours",
    "flight_cycles",
    "rent_rate",
    "rent_inflow",
    "maintenance_reserve_inflow",
    "total_contract_inflow",
)


@dataclass(frozen=True)
class ContractCashflowResult:
    """V2.2 period summary and component-account detail tables."""

    periods: pd.DataFrame
    reserve_accounts: pd.DataFrame


def annual_escalation_periods(current_date: date, base_date: date) -> int:
    """Use the verified V1 January-reset escalation convention."""

    return current_date.year - base_date.year


def escalated_amount(
    base_amount: Decimal, annual_escalation: Decimal, base_date: date, current_date: date
) -> Decimal:
    periods = annual_escalation_periods(current_date, base_date)
    return base_amount * (Decimal("1") + annual_escalation) ** periods


def _fixed_charge_factor(
    lease: LeaseContract, modeled_day_count: int, days_in_month: int
) -> Decimal:
    if lease.fixed_cash_proration is ProrationConvention.ACTUAL_DAYS:
        return Decimal(modeled_day_count) / Decimal(days_in_month)
    return Decimal("1") if modeled_day_count else Decimal("0")


def _reserve_units(
    rule: ReserveAccountRule,
    fixed_charge_factor: Decimal,
    flight_hours: Decimal,
    flight_cycles: Decimal,
) -> Decimal:
    if rule.reserve_basis is ReserveBasis.PER_MONTH:
        return fixed_charge_factor
    if rule.reserve_basis is ReserveBasis.PER_FLIGHT_HOUR:
        return flight_hours
    if rule.reserve_basis is ReserveBasis.PER_FLIGHT_CYCLE:
        return flight_cycles
    raise ValueError(
        f"reserve account {rule.account_id!r} requires contractual rate terms"
    )


def build_contract_cashflows(scenario: Scenario) -> ContractCashflowResult:
    """Calculate rent and reserve inflows for every modeled lease period.

    The period end is the cash-ledger date. `contractual_due_date` is retained for
    audit display, while the expiry-period row always remains inside the lease and
    is therefore available to maintenance and close-out settlement in V2.3.
    """

    utilization = build_lifecycle_utilization(scenario)
    period_rows: list[dict[str, object]] = []
    account_rows: list[dict[str, object]] = []
    period_number = 0

    for lease in sorted(scenario.leases, key=lambda item: item.start_date):
        for contract_period in build_contract_periods(
            lease.start_date, lease.end_date, lease.due_day
        ):
            usage = utilization.loc[
                (utilization["segment_id"] == lease.contract_id)
                & (utilization["segment_type"] == "lease")
                & (utilization["start_date"] >= contract_period.start_date)
                & (utilization["date"] <= contract_period.end_date)
            ]
            if usage.empty:
                continue

            modeled_day_count = int(usage["day_count"].sum())
            flight_hours = sum(usage["flight_hours"], Decimal("0"))
            flight_cycles = sum(usage["flight_cycles"], Decimal("0"))
            fixed_factor = _fixed_charge_factor(
                lease, modeled_day_count, contract_period.days_in_month
            )
            rent_rate = escalated_amount(
                lease.monthly_rent,
                lease.annual_rent_escalation,
                lease.rent_base_date,  # type: ignore[arg-type]
                contract_period.end_date,
            )
            rent_inflow = rent_rate * fixed_factor
            period_number += 1
            reserve_total = Decimal("0")

            for rule in lease.reserve_accounts:
                if rule.rate_base_date is None:
                    raise ValueError(
                        f"reserve account {rule.account_id!r} requires rate_base_date"
                    )
                reserve_rate = escalated_amount(
                    rule.base_rate,
                    rule.annual_escalation,
                    rule.rate_base_date,
                    contract_period.end_date,
                )
                units = _reserve_units(
                    rule, fixed_factor, flight_hours, flight_cycles
                )
                reserve_inflow = reserve_rate * units
                reserve_total += reserve_inflow
                account_rows.append(
                    {
                        "date": contract_period.end_date,
                        "period": period_number,
                        "lease_id": lease.contract_id,
                        "lessee": lease.lessee,
                        "period_start": contract_period.start_date,
                        "period_end": contract_period.end_date,
                        "contractual_due_date": contract_period.due_date,
                        "is_expiry_period": contract_period.end_date == lease.end_date,
                        "is_stub": contract_period.is_stub,
                        "modeled_day_count": modeled_day_count,
                        "days_in_month": contract_period.days_in_month,
                        "fixed_charge_factor": fixed_factor,
                        "flight_hours": flight_hours,
                        "flight_cycles": flight_cycles,
                        "account_id": rule.account_id,
                        "component_code": rule.component_code,
                        "reserve_basis": rule.reserve_basis.value,
                        "reserve_rate": reserve_rate,
                        "reserve_units": units,
                        "reserve_inflow": reserve_inflow,
                    }
                )

            period_rows.append(
                {
                    "date": contract_period.end_date,
                    "period": period_number,
                    "lease_id": lease.contract_id,
                    "lessee": lease.lessee,
                    "period_start": contract_period.start_date,
                    "period_end": contract_period.end_date,
                    "contractual_due_date": contract_period.due_date,
                    "is_expiry_period": contract_period.end_date == lease.end_date,
                    "is_stub": contract_period.is_stub,
                    "modeled_day_count": modeled_day_count,
                    "days_in_month": contract_period.days_in_month,
                    "fixed_charge_factor": fixed_factor,
                    "flight_hours": flight_hours,
                    "flight_cycles": flight_cycles,
                    "rent_rate": rent_rate,
                    "rent_inflow": rent_inflow,
                    "maintenance_reserve_inflow": reserve_total,
                    "total_contract_inflow": rent_inflow + reserve_total,
                }
            )

    return ContractCashflowResult(
        periods=pd.DataFrame(period_rows, columns=LEASE_CASHFLOW_COLUMNS),
        reserve_accounts=pd.DataFrame(
            account_rows, columns=RESERVE_ACCOUNT_INFLOW_COLUMNS
        ),
    )
