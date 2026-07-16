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
        self.assertEqual(self.payload["run"]["valuation_basis"], "nominal_cashflow")
        self.assertEqual(self.payload["summary"]["lease_count"], 2)
        self.assertEqual(self.payload["summary"]["transition_count"], 2)
        self.assertNotIn("valuation_summary", self.payload)
        self.assertNotIn("baseline_id", self.payload)

    def test_payload_contains_complete_audit_tables(self) -> None:
        for section in (
            "scenario", "utilization", "contract_periods", "reserve_accounts",
            "events", "component_states", "redelivery", "reserve_ledger",
            "transition_cashflows", "cashflows",
        ):
            self.assertIn(section, self.payload)
        self.assertTrue(self.payload["utilization"])
        self.assertTrue(self.payload["cashflows"])

    def test_lease_unfunded_is_not_lessor_cash_outflow(self) -> None:
        cash = self.payload["cashflows"]
        expected = sum(
            Decimal(row["rent_inflow"])
            + Decimal(row["maintenance_reserve_inflow"])
            + Decimal(row["redelivery_cash_inflow"])
            - Decimal(row["reserve_reimbursement_outflow"])
            - Decimal(row["lessor_direct_maintenance_outflow"])
            - Decimal(row["reserve_refund_outflow"])
            - Decimal(row["transition_cost"])
            for row in cash
        )
        self.assertEqual(
            expected, Decimal(self.payload["summary"]["nominal_net_lessor_cashflow"])
        )
        self.assertGreater(Decimal(self.payload["summary"]["total_lessee_unfunded"]), 0)

    def test_arbitrary_future_lease_can_be_added(self) -> None:
        inputs = default_scenario_input()
        inputs["segments"][-1]["end_date"] = "2032-02-29"
        inputs["segments"].extend([
            {
                "type": "lease", "id": "follow-on-2", "lessee": "Airline B",
                "start_date": "2032-03-01", "end_date": "2033-06-30",
                "monthly_rent": "320000", "monthly_fh": "230", "monthly_fc": "85",
                "reserve_rate_multiplier": "1.1", "redelivery_minimum_ratio": "0.4",
                "closeout_rule": "retain_by_lessor",
            },
            {
                "type": "transition", "id": "final-holding",
                "description": "Final holding", "start_date": "2033-07-01",
                "end_date": "2033-12-31", "monthly_fh": "0", "monthly_fc": "0",
                "monthly_cost": "30000", "fixed_cost": "0",
            },
        ])
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
        self.assertIsInstance(self.payload["summary"]["total_rent"], str)


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
        self.assertIn("Duplicate scenario", html)
        self.assertIn("Lessee unfunded", script)
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
