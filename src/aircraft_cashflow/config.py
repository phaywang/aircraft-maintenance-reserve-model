"""Illustrative default inputs for the public demonstration model."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from .models import CaseInputs, ComponentConfig, EventDriver, ReserveBasis


DEMO_BASE_DATE = date(2017, 6, 30)


def build_default_case() -> CaseInputs:
    """Build a validated, synthetic narrowbody demonstration case."""

    # Reserve rates are deliberately calibrated to create a useful mix of
    # funded, near-threshold and materially underfunded forecast events.

    airframe_6y = ComponentConfig(
        code="6Y",
        name="Airframe 6Y Check",
        event_driver=EventDriver.CALENDAR_MONTHS,
        interval=72,
        base_cost=Decimal("720000"),
        cost_base_date=DEMO_BASE_DATE,
        annual_cost_escalation=Decimal("0.032"),
        reserve_basis=ReserveBasis.PER_MONTH,
        base_reserve_rate=Decimal("11500"),
        reserve_rate_base_date=DEMO_BASE_DATE,
        annual_reserve_escalation=Decimal("0.028"),
    )
    airframe_12y = ComponentConfig(
        code="12Y",
        name="Airframe 12Y Check",
        event_driver=EventDriver.CALENDAR_MONTHS,
        interval=144,
        base_cost=Decimal("1050000"),
        cost_base_date=DEMO_BASE_DATE,
        annual_cost_escalation=Decimal("0.032"),
        reserve_basis=ReserveBasis.PER_MONTH,
        base_reserve_rate=Decimal("8800"),
        reserve_rate_base_date=DEMO_BASE_DATE,
        annual_reserve_escalation=Decimal("0.028"),
    )
    landing_gear = ComponentConfig(
        code="LDG",
        name="Landing Gear Overhaul",
        event_driver=EventDriver.FLIGHT_CYCLES,
        interval=13000,
        base_cost=Decimal("480000"),
        cost_base_date=DEMO_BASE_DATE,
        annual_cost_escalation=Decimal("0.035"),
        reserve_basis=ReserveBasis.PER_FLIGHT_CYCLE,
        base_reserve_rate=Decimal("47"),
        reserve_rate_base_date=DEMO_BASE_DATE,
        annual_reserve_escalation=Decimal("0.03"),
        usage_since_event_at_lease_start=Decimal("0"),
    )

    def engine(code: str, name: str) -> ComponentConfig:
        return ComponentConfig(
            code=code,
            name=name,
            event_driver=EventDriver.FLIGHT_HOURS,
            interval=15000,
            base_cost=Decimal("3900000"),
            cost_base_date=DEMO_BASE_DATE,
            annual_cost_escalation=Decimal("0.042"),
            reserve_basis=ReserveBasis.PER_FLIGHT_HOUR,
            base_reserve_rate=Decimal("265"),
            reserve_rate_base_date=DEMO_BASE_DATE,
            annual_reserve_escalation=Decimal("0.045"),
            usage_since_event_at_lease_start=Decimal("0"),
        )

    return CaseInputs(
        aircraft_type="A320-200",
        date_of_manufacture=DEMO_BASE_DATE,
        lessee="AeroVista Airlines",
        lease_start_date=DEMO_BASE_DATE,
        analysis_date=date(2026, 6, 30),
        lease_expiry_date=date(2029, 6, 30),
        default_monthly_fh=Decimal("260"),
        default_monthly_fc=Decimal("95"),
        components=(
            airframe_6y,
            airframe_12y,
            landing_gear,
            engine("E1", "Engine 1 Performance Restoration"),
            engine("E2", "Engine 2 Performance Restoration"),
        ),
    )
