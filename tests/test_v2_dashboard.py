"""V2.6 scenario-comparison dashboard contract and frontend tests."""

from __future__ import annotations

import json
import unittest
from decimal import Decimal
from pathlib import Path

from aircraft_cashflow.v2_dashboard_service import build_v2_dashboard_payload


class V2DashboardServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = build_v2_dashboard_payload()

    def test_payload_contains_complete_alternative_audit_tables(self) -> None:
        self.assertEqual(set(self.payload["alternatives"]), {"30-month", "42-month"})
        for alternative in self.payload["alternatives"].values():
            for section in (
                "scenario", "utilization", "contract_periods", "reserve_accounts",
                "events", "component_states", "redelivery", "reserve_ledger",
                "transition_cashflows", "cashflows",
            ):
                self.assertIn(section, alternative)
            self.assertTrue(alternative["utilization"])
            self.assertTrue(alternative["cashflows"])

    def test_payload_uses_common_horizon_and_incremental_npv(self) -> None:
        self.assertEqual(self.payload["comparison"]["common_horizon"], "2033-12-31")
        summary = {row["alternative_id"]: row for row in self.payload["valuation_summary"]}
        self.assertEqual(Decimal(summary["30-month"]["incremental_npv"]), Decimal("0"))
        self.assertNotEqual(Decimal(summary["42-month"]["incremental_npv"]), Decimal("0"))

    def test_editable_follow_on_input_recalculates_full_comparison(self) -> None:
        changed = build_v2_dashboard_payload(
            alternative_inputs={"30-month": {"monthly_rent": "400000"}}
        )
        original_npv = next(
            row["npv"] for row in self.payload["valuation_summary"]
            if row["alternative_id"] == "30-month"
        )
        changed_npv = next(
            row["npv"] for row in changed["valuation_summary"]
            if row["alternative_id"] == "30-month"
        )
        self.assertGreater(Decimal(changed_npv), Decimal(original_npv))
        self.assertEqual(changed["editable_inputs"]["30-month"]["monthly_rent"], "400000")

    def test_payload_is_json_serializable_without_financial_floats(self) -> None:
        encoded = json.dumps(self.payload)
        self.assertIn('"calculation_engine": "deterministic"', encoded)
        self.assertIsInstance(self.payload["valuation_summary"][0]["npv"], str)


class V2DashboardFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1] / "dashboard" / "v2"

    def test_frontend_has_six_decision_views_and_local_run(self) -> None:
        html = (self.root / "index.html").read_text(encoding="utf-8")
        script = (self.root / "app.js").read_text(encoding="utf-8")
        for view in ("overview", "alternatives", "utilization", "settlement", "valuation", "audit"):
            self.assertIn(f'data-view="{view}"', html)
        self.assertIn('fetch("/api/v2/runs"', script)
        self.assertIn("data-field=", script)
        self.assertIn("follow_end", script)
        self.assertIn("annual_discount_rate", script)

    def test_static_and_pages_assets_are_complete(self) -> None:
        pages = Path(__file__).resolve().parents[1] / "docs" / "v2"
        for root in (self.root, pages):
            for filename in ("index.html", "styles.css", "app.js", "dashboard-data.js", "dashboard-data.json"):
                self.assertTrue((root / filename).is_file(), str(root / filename))
            payload = json.loads((root / "dashboard-data.json").read_text(encoding="utf-8"))
            self.assertEqual(len(payload["valuation_summary"]), 2)


if __name__ == "__main__":
    unittest.main()
