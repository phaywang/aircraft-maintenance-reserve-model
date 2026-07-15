from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from aircraft_cashflow.config import build_default_case
from aircraft_cashflow.models import ComponentConfig, EventDriver, ReserveBasis, UtilizationOverride


class InputValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = build_default_case()

    def test_invalid_date_order_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "manufacture <= lease start"):
            replace(self.case, analysis_date=date(2017, 5, 31))

    def test_negative_default_utilization_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "default_monthly_fh must be nonnegative"):
            replace(self.case, default_monthly_fh=-1)

    def test_duplicate_component_codes_are_rejected(self) -> None:
        duplicate = replace(self.case.components[0], name="Duplicate")
        with self.assertRaisesRegex(ValueError, "component codes must be unique"):
            replace(self.case, components=self.case.components + (duplicate,))

    def test_non_month_end_override_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "month-end"):
            UtilizationOverride(date(2024, 1, 15), 250, 100)

    def test_override_outside_lease_is_rejected(self) -> None:
        override = UtilizationOverride(date(2030, 1, 31), 260, 95)
        with self.assertRaisesRegex(ValueError, "within the lease term"):
            replace(self.case, utilization_overrides=(override,))

    def test_zero_interval_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "interval must be greater than zero"):
            ComponentConfig(
                code="TEST",
                name="Test component",
                event_driver=EventDriver.FLIGHT_HOURS,
                interval=0,
                base_cost=100,
                cost_base_date=date(2020, 1, 31),
                annual_cost_escalation=Decimal("0.03"),
                reserve_basis=ReserveBasis.PER_FLIGHT_HOUR,
                base_reserve_rate=10,
                reserve_rate_base_date=date(2020, 1, 31),
                annual_reserve_escalation=Decimal("0.03"),
            )

    def test_calendar_component_rejects_usage_since_event(self) -> None:
        with self.assertRaisesRegex(ValueError, "calendar-driven"):
            replace(
                self.case.components[0],
                usage_since_event_at_lease_start=Decimal("10"),
            )


if __name__ == "__main__":
    unittest.main()
