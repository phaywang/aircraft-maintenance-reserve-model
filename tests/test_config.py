from __future__ import annotations

import unittest
from decimal import Decimal

from aircraft_cashflow.config import build_default_case
from aircraft_cashflow.models import EventDriver, ReserveBasis


class DefaultConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = build_default_case()
        self.components = {component.code: component for component in self.case.components}

    def test_case_header_matches_public_demo(self) -> None:
        self.assertEqual(self.case.aircraft_type, "A320-200")
        self.assertEqual(self.case.lessee, "AeroVista Airlines")
        self.assertEqual(self.case.default_monthly_fh, Decimal("260"))
        self.assertEqual(self.case.default_monthly_fc, Decimal("95"))
        self.assertEqual(self.case.lease_start_date.isoformat(), "2017-06-30")
        self.assertEqual(self.case.analysis_date.isoformat(), "2026-06-30")
        self.assertEqual(self.case.lease_expiry_date.isoformat(), "2029-06-30")

    def test_all_five_components_are_separate(self) -> None:
        self.assertEqual(set(self.components), {"6Y", "12Y", "LDG", "E1", "E2"})
        self.assertIsNot(self.components["E1"], self.components["E2"])

    def test_component_intervals_match_demo_configuration(self) -> None:
        self.assertEqual(self.components["6Y"].interval, Decimal("72"))
        self.assertEqual(self.components["12Y"].interval, Decimal("144"))
        self.assertEqual(self.components["LDG"].interval, Decimal("13000"))
        self.assertEqual(self.components["E1"].interval, Decimal("15000"))
        self.assertEqual(self.components["E2"].interval, Decimal("15000"))

    def test_component_drivers_and_reserve_bases(self) -> None:
        self.assertIs(
            self.components["6Y"].event_driver, EventDriver.CALENDAR_MONTHS
        )
        self.assertIs(self.components["LDG"].event_driver, EventDriver.FLIGHT_CYCLES)
        self.assertIs(self.components["E1"].event_driver, EventDriver.FLIGHT_HOURS)
        self.assertIs(self.components["6Y"].reserve_basis, ReserveBasis.PER_MONTH)
        self.assertIs(
            self.components["LDG"].reserve_basis, ReserveBasis.PER_FLIGHT_CYCLE
        )
        self.assertIs(
            self.components["E1"].reserve_basis, ReserveBasis.PER_FLIGHT_HOUR
        )

    def test_serialized_configuration_contains_no_decimal_or_date_objects(self) -> None:
        payload = self.case.to_dict()
        self.assertEqual(payload["default_monthly_fh"], "260")
        self.assertEqual(payload["lease_expiry_date"], "2029-06-30")
        self.assertEqual(payload["components"][0]["event_driver"], "calendar_months")


if __name__ == "__main__":
    unittest.main()
