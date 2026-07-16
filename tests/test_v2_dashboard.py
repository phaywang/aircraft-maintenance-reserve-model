"""V2.1 lessor scenario-builder service and frontend contract tests."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path

from aircraft_cashflow.balances import (
    build_forecast_reserve_balances,
    closing_balance_column,
    event_cost_column,
    reserve_outflow_column,
    unfunded_amount_column,
)
from aircraft_cashflow.config import build_default_case
from aircraft_cashflow.inflows import reserve_inflow_column
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
            "reserve_cashflows", "resolved_known_state",
        ):
            self.assertIn(section, self.payload)
        self.assertTrue(self.payload["utilization"])
        self.assertTrue(self.payload["reserve_cashflows"])

    def test_single_lease_v2_matches_verified_v1_monthly_rollforward(self) -> None:
        case = build_default_case()
        inputs = default_scenario_input()
        inputs["segments"] = [inputs["segments"][0]]
        inputs["forecast_end_date"] = case.lease_expiry_date.isoformat()
        inputs["segments"][0]["redelivery_minimum_ratio"] = "0"
        result = build_scenario_payload(inputs)
        v1 = build_forecast_reserve_balances(case)
        v1_by_date = {row.date: row for row in v1.itertuples(index=False)}

        opening = v1.loc[v1["date"] == case.analysis_date].iloc[0]
        for component in case.components:
            code = component.code
            self.assertEqual(
                Decimal(result["resolved_known_state"]["reserve_balances"][code]),
                Decimal(opening[closing_balance_column(code)]),
            )

        for row in result["reserve_ledger"]:
            reference = v1_by_date[date.fromisoformat(str(row["date"]))]
            code = str(row["component_code"])
            self.assertEqual(
                Decimal(str(row["reserve_inflow"])),
                Decimal(str(getattr(reference, reserve_inflow_column(code)))),
            )
            self.assertEqual(
                Decimal(str(row["event_cost"])),
                Decimal(str(getattr(reference, event_cost_column(code)))),
            )
            self.assertEqual(
                Decimal(str(row["reserve_reimbursement"])),
                Decimal(str(getattr(reference, reserve_outflow_column(code)))),
            )
            self.assertEqual(
                Decimal(str(row["unfunded_amount"])),
                Decimal(str(getattr(reference, unfunded_amount_column(code)))),
            )
            self.assertEqual(
                Decimal(str(row["balance_before_closeout"])),
                Decimal(str(getattr(reference, closing_balance_column(code)))),
            )

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

    def test_comparison_summary_contains_normalized_funding_metrics(self) -> None:
        summary = self.payload["summary"]
        for field in (
            "forecast_months", "total_flight_hours", "total_flight_cycles",
            "largest_lessee_top_up", "reserve_funding_coverage",
        ):
            self.assertIn(field, summary)
        expected = (
            Decimal(summary["total_reserve_reimbursement"])
            / Decimal(summary["total_event_cost"])
        )
        self.assertEqual(expected, Decimal(summary["reserve_funding_coverage"]))

    def test_default_opening_state_is_reconstructed_from_history(self) -> None:
        state = self.payload["resolved_known_state"]
        self.assertEqual(state["basis"], "reconstructed")
        self.assertEqual(state["ttsn"], "28080")
        self.assertEqual(state["tcsn"], "10260")
        self.assertEqual(state["component_last_event_dates"]["6Y"], "2023-06-30")
        self.assertEqual(state["reserve_balance_source"], "historical_lease_rollforward")
        self.assertGreater(Decimal(state["reserve_balances"]["E1"]), 0)

    def test_reconstructed_state_ignores_manual_opening_values(self) -> None:
        inputs = default_scenario_input()
        inputs["known_state"]["ttsn"] = "1"
        inputs["known_state"]["tcsn"] = "1"
        inputs["known_state"]["reserve_balances"] = {"6Y": "1"}
        result = build_scenario_payload(inputs)
        state = result["resolved_known_state"]
        self.assertEqual(state["ttsn"], "28080")
        self.assertNotEqual(Decimal(state["reserve_balances"]["6Y"]), Decimal("1"))

    def test_actual_state_mode_respects_user_records(self) -> None:
        inputs = default_scenario_input()
        inputs["known_state"]["basis"] = "actual"
        inputs["known_state"]["ttsn"] = "28123.5"
        inputs["known_state"]["tcsn"] = "10270"
        inputs["known_state"]["component_last_event_dates"] = {}
        inputs["known_state"]["reserve_balances"]["6Y"] = "123.45"
        result = build_scenario_payload(inputs)
        state = result["resolved_known_state"]
        self.assertEqual(state["ttsn"], "28123.5")
        self.assertEqual(state["reserve_balances"]["6Y"], "123.45")
        self.assertEqual(state["component_last_event_dates"], {})

    def test_reconstructed_opening_reserve_responds_to_active_lease_terms(self) -> None:
        base = default_scenario_input()
        changed = deepcopy(base)
        changed["segments"][0]["reserve_rate_multiplier"] = "1.2"
        base_balance = Decimal(
            build_scenario_payload(base)["resolved_known_state"]["reserve_balances"]["12Y"]
        )
        changed_balance = Decimal(
            build_scenario_payload(changed)["resolved_known_state"]["reserve_balances"]["12Y"]
        )
        self.assertGreater(changed_balance, base_balance)

    def test_component_rate_override_changes_only_target_account(self) -> None:
        base_inputs = default_scenario_input()
        changed_inputs = deepcopy(base_inputs)
        changed_inputs["segments"][0]["reserve_rates"] = {"6Y": "20000"}
        base = build_scenario_payload(base_inputs)["reserve_accounts"]
        changed = build_scenario_payload(changed_inputs)["reserve_accounts"]

        def first_rate(rows: list[dict[str, object]], component: str) -> Decimal:
            row = next(
                item for item in rows
                if item["lease_id"] == "lease-1"
                and item["component_code"] == component
            )
            return Decimal(str(row["reserve_rate"]))

        self.assertGreater(first_rate(changed, "6Y"), first_rate(base, "6Y"))
        self.assertEqual(first_rate(changed, "12Y"), first_rate(base, "12Y"))

    def test_custom_maintenance_cost_changes_only_target_component(self) -> None:
        base_inputs = default_scenario_input()
        changed_inputs = deepcopy(base_inputs)
        e1 = next(
            item for item in changed_inputs["maintenance_program"]
            if item["code"] == "E1"
        )
        e1["base_cost"] = str(Decimal(e1["base_cost"]) * Decimal("1.25"))
        base = build_scenario_payload(base_inputs)["events"]
        changed = build_scenario_payload(changed_inputs)["events"]

        def event_cost(rows: list[dict[str, object]], component: str) -> Decimal:
            return sum(
                (Decimal(str(row["event_cost"])) for row in rows if row["component_code"] == component),
                Decimal("0"),
            )

        self.assertGreater(event_cost(changed, "E1"), event_cost(base, "E1"))
        self.assertEqual(event_cost(changed, "E2"), event_cost(base, "E2"))

    def test_component_reserve_escalation_override_is_lease_specific(self) -> None:
        base_inputs = default_scenario_input()
        changed_inputs = deepcopy(base_inputs)
        changed_inputs["segments"][0]["reserve_escalations"] = {"6Y": "0.10"}
        base = build_scenario_payload(base_inputs)["reserve_accounts"]
        changed = build_scenario_payload(changed_inputs)["reserve_accounts"]

        def first_rate(rows: list[dict[str, object]], component: str) -> Decimal:
            row = next(
                item for item in rows
                if item["lease_id"] == "lease-1"
                and item["component_code"] == component
            )
            return Decimal(str(row["reserve_rate"]))

        self.assertGreater(first_rate(changed, "6Y"), first_rate(base, "6Y"))
        self.assertEqual(first_rate(changed, "12Y"), first_rate(base, "12Y"))

    def test_reconstruction_uses_each_historical_lease_utilization(self) -> None:
        inputs = default_scenario_input()
        inputs["segments"][0]["end_date"] = "2024-06-30"
        inputs["segments"][1]["start_date"] = "2024-07-01"
        inputs["segments"][1]["monthly_fh"] = "200"
        inputs["segments"][1]["monthly_fc"] = "80"
        state = build_scenario_payload(inputs)["resolved_known_state"]
        self.assertEqual(state["active_lease_id"], "follow-on-1")
        self.assertEqual(state["ttsn"], "26640")
        self.assertEqual(state["tcsn"], "9900")
        self.assertTrue(all(Decimal(value) >= 0 for value in state["reserve_balances"].values()))

    def test_blank_actual_calendar_date_uses_theoretical_prior_event(self) -> None:
        inputs = default_scenario_input()
        inputs["known_state"]["basis"] = "actual"
        inputs["known_state"]["component_last_event_dates"] = {}
        inputs["segments"][0]["end_date"] = "2028-06-30"
        inputs["segments"][1]["start_date"] = "2028-07-01"
        result = build_scenario_payload(inputs)
        state = next(
            row for row in result["component_states"]
            if row["lease_id"] == "lease-1" and row["component_code"] == "6Y"
        )
        self.assertGreater(Decimal(state["remaining_units"]), Decimal("11"))
        self.assertLess(Decimal(state["remaining_units"]), Decimal("13"))

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
        for control in (
            "new-scenario", "duplicate-scenario", "rename-scenario",
            "delete-scenario", "run-all", "save-workspace",
        ):
            self.assertIn(f'id="{control}"', html)
        self.assertIn("localStorage", script)
        self.assertIn("Reconstruct from history", script)
        self.assertIn("Actual known state", script)
        self.assertIn("Opening-state provenance", script)
        self.assertIn("data-compare-index", script)
        self.assertIn("Lessee top-up required", script)
        self.assertIn("Lease-end technical position", script)
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

    def test_decision_workflow_progressive_disclosure_and_accessibility(self) -> None:
        html = (self.root / "index.html").read_text(encoding="utf-8")
        script = (self.root / "app.js").read_text(encoding="utf-8")
        styles = (self.root / "styles.css").read_text(encoding="utf-8")
        for label in (
            "Scenario inputs", "Current scenario", "Cross-scenario decision",
            "Model assurance",
        ):
            self.assertIn(label, html)
        for feature in (
            "Historical", "Active at analysis", "Proposed", "Copy prior terms",
            "Top-up only", "data-event-detail", "Full monthly reserve ledger",
            "Comparison baseline", "Inputs changed since the last run",
            "Component funding comparison", "data-cashflow-component",
            "Component reserve rates", "data-reserve-rate",
            "Technical event assumptions", "data-maintenance-index",
            "data-reserve-escalation", "Balance before close-out",
            "Current scenario analysis", "04 Event funding",
            "05 Reserve accounts", "06 Cash-flow detail",
        ):
            self.assertIn(feature, script)
        self.assertIn('scope="col"', script)
        self.assertIn('aria-busy="false"', html)
        self.assertIn(":focus-visible", styles)
        self.assertIn("Aggregate reserve balance", script)
        self.assertNotIn("best scenario", script.lower())

    def test_static_and_pages_assets_are_complete_and_synchronized(self) -> None:
        pages = Path(__file__).resolve().parents[1] / "docs" / "v2"
        for root in (self.root, pages):
            for filename in ("index.html", "styles.css", "app.js", "dashboard-data.js", "dashboard-data.json"):
                self.assertTrue((root / filename).is_file(), str(root / filename))
        payload = json.loads((self.root / "dashboard-data.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["run"]["perspective"], "lessor")


if __name__ == "__main__":
    unittest.main()
