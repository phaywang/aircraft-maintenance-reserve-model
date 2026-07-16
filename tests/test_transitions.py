"""V2.4 transition economics and lifecycle alternative tests."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from aircraft_cashflow.lifecycle import (
    AircraftAsset, CutoffPosition, LeaseContract, ReserveAccountRule, Scenario,
    TransitionCost, TransitionPeriod, UtilizationRegime,
)
from aircraft_cashflow.models import ComponentConfig, EventDriver, ReserveBasis
from aircraft_cashflow.transitions import (
    AlternativeSet, ScenarioAlternative, build_lifecycle_economics,
    build_transition_cashflows,
)


class TransitionEconomicsTests(unittest.TestCase):
    def setUp(self) -> None:
        component = ComponentConfig(
            "E1", "Engine", EventDriver.FLIGHT_HOURS, 100000, 1000,
            date(2027, 1, 1), 0, ReserveBasis.PER_FLIGHT_HOUR, 0,
            date(2027, 1, 1), 0, usage_since_event_at_lease_start=0,
        )
        self.asset = AircraftAsset(
            "asset", "Test Aircraft", date(2027, 1, 1), (component,)
        )
        self.lease_1 = LeaseContract(
            "lease-1", "Airline A", date(2027, 1, 1), date(2027, 1, 14),
            (ReserveAccountRule("lease-1:E1", "E1", ReserveBasis.PER_FLIGHT_HOUR, 0, date(2027, 1, 1)),),
            monthly_rent=31000,
        )
        self.transition = TransitionPeriod(
            "transition", date(2027, 1, 15), date(2027, 2, 10), "Preparation",
            monthly_cost=3100, fixed_cost=1000,
            costs=(TransitionCost("ferry", date(2027, 1, 20), 500, "ferry"),),
        )
        self.lease_2 = LeaseContract(
            "lease-2", "Airline B", date(2027, 2, 11), date(2027, 2, 28),
            (ReserveAccountRule("lease-2:E1", "E1", ReserveBasis.PER_FLIGHT_HOUR, 0, date(2027, 2, 11)),),
            monthly_rent=28000,
        )

    def scenario(self, lease_2: LeaseContract | None = None) -> Scenario:
        lease_2 = lease_2 or self.lease_2
        regimes = (
            UtilizationRegime("use-1", "lease-1", self.lease_1.start_date, self.lease_1.end_date, 140, 70),
            UtilizationRegime("ground", "transition", self.transition.start_date, self.transition.end_date, 0, 0),
            UtilizationRegime("use-2", "lease-2", lease_2.start_date, lease_2.end_date, 180, 90),
        )
        return Scenario(
            "transition-test", "Transition test", self.asset,
            self.lease_1.end_date, CutoffPosition.AFTER_EXPIRY_SETTLEMENT,
            self.lease_1.end_date, lease_2.end_date,
            (self.lease_1, lease_2), regimes, (self.transition,),
        )

    def test_transition_monthly_fixed_and_explicit_costs_are_separate(self) -> None:
        rows = build_transition_cashflows(self.scenario())
        self.assertEqual(list(rows["date"]), [
            date(2027, 1, 15), date(2027, 1, 20), date(2027, 1, 31), date(2027, 2, 10)
        ])
        self.assertEqual(sum(rows["fixed_cost"], Decimal("0")), Decimal("1000"))
        self.assertEqual(sum(rows["explicit_cost"], Decimal("0")), Decimal("500"))
        monthly = Decimal("3100") * Decimal("17") / Decimal("31") + Decimal("3100") * Decimal("10") / Decimal("28")
        self.assertEqual(sum(rows["monthly_cost"], Decimal("0")), monthly)

    def test_transition_cost_reduces_combined_owner_cashflow(self) -> None:
        result = build_lifecycle_economics(self.scenario())
        self.assertEqual(
            sum(result.cashflows["transition_cost"], Decimal("0")),
            sum(result.transition_cashflows["total_transition_cost"], Decimal("0")),
        )
        self.assertEqual(
            sum(result.cashflows["net_owner_cashflow"], Decimal("0")),
            sum(result.settlement.cashflows["net_owner_cashflow"], Decimal("0"))
            - sum(result.transition_cashflows["total_transition_cost"], Decimal("0")),
        )

    def test_alternative_set_accepts_arbitrary_follow_on_duration(self) -> None:
        longer_lease = replace(self.lease_2, end_date=date(2027, 3, 31))
        alternatives = AlternativeSet(
            "follow-on-choice",
            (
                ScenarioAlternative("short", "Short follow-on", self.scenario()),
                ScenarioAlternative("long", "Long follow-on", self.scenario(longer_lease)),
            ),
        )
        self.assertEqual(len(alternatives.alternatives), 2)
        self.assertNotEqual(
            alternatives.alternatives[0].scenario.comparison_horizon,
            alternatives.alternatives[1].scenario.comparison_horizon,
        )

    def test_alternative_set_rejects_duplicate_ids(self) -> None:
        item = ScenarioAlternative("same", "Scenario", self.scenario())
        with self.assertRaisesRegex(ValueError, "identifiers must be unique"):
            AlternativeSet("comparison", (item, item))


if __name__ == "__main__":
    unittest.main()
