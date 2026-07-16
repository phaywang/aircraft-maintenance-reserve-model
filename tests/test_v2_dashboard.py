"""V2.1 lessor scenario-builder service and frontend contract tests."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from aircraft_cashflow.scenario_builder import (
    build_scenario_payload,
    compare_scenario_payloads,
    default_scenario_input,
    scenario_from_input,
)


class ScenarioBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = build_scenario_payload()

    def test_default_is_one_independent_multi_lease_scenario(self) -> None:
        self.assertEqual(self.payload["run"]["perspective"], "lessor")
        self.assertEqual(
            self.payload["run"]["valuation_basis"], "maintenance_reserve_cashflow"
        )
        self.assertEqual(self.payload["summary"]["lease_count"], 2)
        self.assertEqual(self.payload["summary"]["transition_count"], 0)
        self.assertNotIn("valuation_summary", self.payload)
        self.assertNotIn("baseline_id", self.payload)

    def test_payload_contains_complete_audit_tables(self) -> None:
        for section in (
            "scenario", "utilization", "contract_periods", "reserve_accounts",
            "events", "component_states", "redelivery", "reserve_ledger",
            "reserve_cashflows",
        ):
            self.assertIn(section, self.payload)
        self.assertTrue(self.payload["utilization"])
        self.assertTrue(self.payload["reserve_cashflows"])

    def test_reserve_cash_movement_reconciles_without_rent(self) -> None:
        cash = self.payload["reserve_cashflows"]
        expected = sum(
            Decimal(row["reserve_inflow"])
            - Decimal(row["reserve_outflow"])
            - Decimal(row["refund_to_lessee"])
            for row in cash
        )
        self.assertEqual(
            expected, Decimal(self.payload["summary"]["net_reserve_cash_movement"])
        )
        self.assertGreater(Decimal(self.payload["summary"]["total_lessee_unfunded"]), 0)
        self.assertNotIn("total_rent", self.payload["summary"])
        self.assertNotIn("monthly_rent", self.payload["scenario_input"]["segments"][0])
        self.assertNotIn("monthly_rent", self.payload["scenario"]["leases"][0])

    def test_arbitrary_future_lease_can_be_added(self) -> None:
        inputs = default_scenario_input()
        inputs["segments"][-1]["end_date"] = "2032-02-29"
        inputs["forecast_end_date"] = "2033-06-30"
        inputs["segments"].append(
            {
                "type": "lease", "id": "follow-on-2", "lessee": "Airline B",
                "start_date": "2032-03-01", "end_date": "2033-06-30",
                "monthly_fh": "230", "monthly_fc": "85",
                "reserve_rate_multiplier": "1.1", "redelivery_minimum_ratio": "0.4",
                "closeout_rule": "retain_by_lessor",
            }
        )
        result = build_scenario_payload(inputs)
        self.assertEqual(result["summary"]["lease_count"], 3)
        self.assertEqual(len(result["scenario"]["leases"]), 3)

    def test_segment_gap_and_overlap_fail_clearly(self) -> None:
        inputs = default_scenario_input()
        inputs["segments"][1]["start_date"] = "2029-07-02"
        with self.assertRaisesRegex(ValueError, "gap between lifecycle segments"):
            scenario_from_input(inputs)
        inputs = default_scenario_input()
        inputs["segments"][1]["start_date"] = "2029-06-30"
        with self.assertRaisesRegex(ValueError, "overlap"):
            scenario_from_input(inputs)

    def test_comparison_accepts_any_number_and_does_not_mutate_inputs(self) -> None:
        first = default_scenario_input()
        second = deepcopy(first)
        second["scenario_id"] = "extension-plan"
        second["name"] = "Extension plan"
        third = deepcopy(first)
        third["scenario_id"] = "new-lessee-plan"
        third["name"] = "New lessee plan"
        before = deepcopy(first)
        comparison = compare_scenario_payloads([first, second, third])
        self.assertEqual(comparison["scenario_count"], 3)
        self.assertEqual(first, before)

    def test_payload_is_json_serializable_without_financial_floats(self) -> None:
        encoded = json.dumps(self.payload)
        self.assertIn('"perspective": "lessor"', encoded)
        self.assertIsInstance(self.payload["summary"]["total_reserve_collections"], str)

    def test_opening_reserve_inputs_are_limited_to_cents(self) -> None:
        balances = default_scenario_input()["known_state"]["reserve_balances"]
        self.assertTrue(balances)
        self.assertTrue(all(Decimal(value).as_tuple().exponent == -2 for value in balances.values()))


class V2DashboardFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1] / "dashboard" / "v2"

    def test_frontend_is_scenario_builder_not_fixed_comparison(self) -> None:
        html = (self.root / "index.html").read_text(encoding="utf-8")
        script = (self.root / "app.js").read_text(encoding="utf-8")
        for view in ("setup", "timeline", "overview", "funding", "reserves", "cashflow", "comparison", "audit"):
            self.assertIn(f'data-view="{view}"', html)
        self.assertIn('fetch("/api/v2/runs"', script)
        self.assertIn("Add lease", script)
        self.assertNotIn("Add transition", script)
        self.assertNotIn("Transition / downtime", script)
        self.assertIn("Duplicate scenario", html)
        self.assertIn("Lessee unfunded", script)
        self.assertIn("reserve_cashflows", script)
        self.assertIn("inputDecimal", script)
        self.assertNotIn("Rent collected", script)
        self.assertNotIn("Monthly rent", script)
        self.assertNotIn("annual_discount_rate", script)
        self.assertNotIn("baseline_id", script)

    def test_v1_and_v2_routes_remain_distinct(self) -> None:
        html = (self.root / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="../">Open V1 case model', html)
        self.assertTrue((self.root.parent / "static" / "index.html").is_file())

    def test_static_and_pages_assets_are_complete_and_synchronized(self) -> None:
        pages = Path(__file__).resolve().parents[1] / "docs" / "v2"
        for root in (self.root, pages):
            for filename in ("index.html", "styles.css", "app.js", "dashboard-data.js", "dashboard-data.json"):
                self.assertTrue((root / filename).is_file(), str(root / filename))
        payload = json.loads((self.root / "dashboard-data.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["run"]["perspective"], "lessor")


if __name__ == "__main__":
    unittest.main()
