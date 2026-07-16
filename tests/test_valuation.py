"""V2.5 common-horizon NPV tests."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from aircraft_cashflow.lifecycle import (
    AircraftAsset, CutoffPosition, LeaseContract, ReserveAccountRule, Scenario,
    TerminalValue, TerminalValueBasis, UtilizationRegime,
)
from aircraft_cashflow.models import ComponentConfig, EventDriver, ReserveBasis
from aircraft_cashflow.transitions import AlternativeSet, ScenarioAlternative
from aircraft_cashflow.valuation import compare_alternatives


class ValuationTests(unittest.TestCase):
    def setUp(self) -> None:
        component = ComponentConfig(
            "E1", "Engine", EventDriver.FLIGHT_HOURS, 100000, 1000,
            date(2027, 1, 1), 0, ReserveBasis.PER_FLIGHT_HOUR, 0,
            date(2027, 1, 1), 0, usage_since_event_at_lease_start=0,
        )
        self.asset = AircraftAsset("asset", "Aircraft", date(2027, 1, 1), (component,))

    def scenario(self, scenario_id: str, rent: int, end: date = date(2027, 1, 31)) -> Scenario:
        account = ReserveAccountRule(
            f"{scenario_id}:E1", "E1", ReserveBasis.PER_FLIGHT_HOUR, 0, date(2027, 1, 1)
        )
        lease = LeaseContract(
            scenario_id, "Airline", date(2027, 1, 1), end, (account,), monthly_rent=rent
        )
        regime = UtilizationRegime("use", scenario_id, lease.start_date, end, 0, 0)
        return Scenario(
            scenario_id, scenario_id, self.asset, date(2027, 1, 1),
            CutoffPosition.AFTER_EXPIRY_SETTLEMENT, date(2027, 1, 1), end,
            (lease,), (regime,),
            terminal_value=TerminalValue(end, 10000, TerminalValueBasis.APPRAISAL, 100),
        )

    def alternatives(self) -> AlternativeSet:
        return AlternativeSet("comparison", (
            ScenarioAlternative("base", "Base", self.scenario("base", 1000)),
            ScenarioAlternative("high", "Higher rent", self.scenario("high", 2000)),
        ))

    def test_zero_rate_npv_and_incremental_npv_reconcile(self) -> None:
        result = compare_alternatives(
            self.alternatives(), 0, "base", date(2027, 1, 31)
        )
        base = result.summary.loc[result.summary["alternative_id"] == "base"].iloc[0]
        high = result.summary.loc[result.summary["alternative_id"] == "high"].iloc[0]
        self.assertEqual(base["npv"], Decimal("10900"))
        self.assertEqual(base["incremental_npv"], Decimal("0"))
        self.assertEqual(high["npv"], Decimal("11900"))
        self.assertEqual(high["incremental_npv"], Decimal("1000"))

    def test_positive_discount_rate_reduces_future_present_value(self) -> None:
        result = compare_alternatives(
            self.alternatives(), "0.10", "base", date(2027, 1, 31)
        )
        terminal = result.discounted_cashflows.loc[
            (result.discounted_cashflows["alternative_id"] == "base")
            & (result.discounted_cashflows["cashflow_type"] == "terminal_value")
        ].iloc[0]
        self.assertLess(terminal["present_value"], terminal["nominal_cashflow"])

    def test_comparison_rejects_an_unmodeled_common_horizon(self) -> None:
        short = self.scenario("short", 1000, date(2027, 1, 15))
        alternatives = AlternativeSet("comparison", (
            ScenarioAlternative("short", "Short", short),
            ScenarioAlternative("base", "Base", self.scenario("base", 1000)),
        ))
        with self.assertRaisesRegex(ValueError, "not modeled through"):
            compare_alternatives(alternatives, 0, "base", date(2027, 1, 31))

    def test_comparison_requires_terminal_value(self) -> None:
        scenario = self.scenario("missing", 1000)
        scenario = Scenario(
            scenario.scenario_id, scenario.name, scenario.asset, scenario.analysis_date,
            scenario.cutoff_position, scenario.valuation_date, scenario.comparison_horizon,
            scenario.leases, scenario.utilization_regimes,
        )
        alternatives = AlternativeSet("comparison", (
            ScenarioAlternative("missing", "Missing", scenario),
            ScenarioAlternative("base", "Base", self.scenario("base", 1000)),
        ))
        with self.assertRaisesRegex(ValueError, "requires terminal value"):
            compare_alternatives(alternatives, 0, "base", date(2027, 1, 31))


if __name__ == "__main__":
    unittest.main()
