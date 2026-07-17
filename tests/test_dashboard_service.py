from __future__ import annotations

import json
import threading
import unittest
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from aircraft_cashflow.api import DashboardRunStore, create_server
from aircraft_cashflow.config import build_default_case
from aircraft_cashflow.dashboard_service import case_from_payload, run_dashboard_case


class DashboardServiceTests(unittest.TestCase):
    def test_demo_case_round_trips_through_request_contract(self) -> None:
        original = build_default_case()
        parsed = case_from_payload(original.to_dict())
        self.assertEqual(parsed.to_dict(), original.to_dict())

    def test_v1_derives_cost_and_rate_dates_from_the_single_lease_timeline(self) -> None:
        payload = build_default_case().to_dict()
        for component in payload["components"]:
            component["cost_base_date"] = "2000-01-01"
            component["reserve_rate_base_date"] = "2001-01-01"

        parsed = case_from_payload(payload)

        for component in parsed.components:
            self.assertEqual(component.cost_base_date, parsed.date_of_manufacture)
            self.assertEqual(component.reserve_rate_base_date, parsed.lease_start_date)

    def test_dashboard_payload_contains_stage_1_through_4(self) -> None:
        payload = run_dashboard_case(build_default_case())
        self.assertEqual(len(payload["utilization"]), 37)
        self.assertEqual(len(payload["maintenance_calendar"]), 37)
        self.assertEqual(len(payload["reserve_inflows"]), 37)
        self.assertEqual(len(payload["cashflows"]), 37)
        self.assertEqual(len(payload["opening_balance_history"]), 108)
        self.assertEqual(len(payload["historical_funding_events"]), 3)
        self.assertEqual(len(payload["funding_events"]), 5)
        self.assertEqual(payload["audit"]["calculation_scope"], ["stage_1", "stage_2", "stage_3", "stage_4"])
        self.assertEqual(payload["audit"]["calculation_engine"], "deterministic")

    def test_summary_metrics_match_verified_stage_4(self) -> None:
        summary = run_dashboard_case(build_default_case())["summary"]
        self.assertEqual(summary["forecast_shortfall"], "785151.723350436147847273156")
        self.assertEqual(summary["lease_end_reserve_balance"], "6339723.741906995985402601186")
        self.assertEqual(summary["component_event_count"], 5)
        self.assertEqual(summary["underfunded_event_count"], 3)

    def test_demo_contains_funded_near_threshold_and_shortfall_events(self) -> None:
        events = {
            event["component"]: event
            for event in run_dashboard_case(build_default_case())["funding_events"]
        }
        self.assertTrue(events["6Y"]["fully_funded"])
        self.assertTrue(events["LDG"]["fully_funded"])
        self.assertFalse(events["12Y"]["fully_funded"])
        self.assertGreater(Decimal(events["12Y"]["coverage_ratio"]), Decimal("0.98"))
        for code in ("E1", "E2"):
            self.assertFalse(events[code]["fully_funded"])
            self.assertGreater(Decimal(events[code]["shortfall"]), Decimal("350000"))

    def test_opening_balance_history_reconciles_to_analysis_date_opening(self) -> None:
        payload = run_dashboard_case(build_default_case())
        history = payload["opening_balance_history"]
        forecast_opening = payload["cashflows"][0]
        self.assertEqual(history[0]["date"], "2017-06-30")
        self.assertEqual(history[-1]["date"], "2026-05-31")
        for code in ("6Y", "12Y", "LDG", "E1", "E2"):
            self.assertEqual(
                history[-1][f"closing_balance_{code}"],
                forecast_opening[f"opening_balance_{code}"],
            )
        for event in payload["historical_funding_events"]:
            self.assertEqual(
                Decimal(event["available_reserve"]),
                Decimal(event["opening_reserve"]) + Decimal(event["current_inflow"]),
            )

    def test_demo_reconciliation_is_only_applicable_to_default_case(self) -> None:
        default_payload = run_dashboard_case(build_default_case())
        modified = build_default_case().to_dict()
        modified["default_monthly_fh"] = "300"
        changed_payload = run_dashboard_case(case_from_payload(modified))
        self.assertTrue(default_payload["audit"]["demo_reconciliation"]["applicable"])
        self.assertEqual(default_payload["audit"]["demo_reconciliation"]["status"], "matched")
        stages = default_payload["audit"]["demo_reconciliation"]["stages"]
        self.assertEqual(stages["stage_1"]["matched_rows"], 37)
        self.assertEqual(stages["stage_2"]["matched_rows"], 37)
        self.assertEqual(stages["stage_3"]["matched_rows"], 37)
        self.assertEqual(stages["stage_4_forecast"]["matched_rows"], 37)
        self.assertEqual(stages["stage_4_history"]["matched_rows"], 109)
        self.assertTrue(all(stage["matched"] for stage in stages.values()))
        self.assertFalse(changed_payload["audit"]["demo_reconciliation"]["applicable"])
        self.assertEqual(changed_payload["audit"]["demo_reconciliation"]["status"], "not_applicable")
        self.assertEqual(changed_payload["audit"]["demo_reconciliation"]["stages"], {})
        self.assertTrue(changed_payload["audit"]["input_changes"])

    def test_runtime_validation_covers_full_lease_and_exact_account_rules(self) -> None:
        payload = run_dashboard_case(build_default_case())
        audit = payload["audit"]
        self.assertEqual(audit["runtime_scope"]["months"], 145)
        self.assertEqual(audit["runtime_scope"]["component_accounts"], 5)
        self.assertEqual(
            set(audit["runtime_checks"]),
            {
                "available_balance_tie_out",
                "opening_continuity",
                "reimbursement_lower_of",
                "rollforward_tie_out",
                "shortfall_tie_out",
                "nonnegative_balances",
                "component_totals_tie_out",
            },
        )
        self.assertTrue(all(check["passed"] for check in audit["runtime_checks"].values()))
        self.assertEqual(
            sum(check["checks"] for check in audit["runtime_checks"].values()),
            4925,
        )
        self.assertIn("input_signature", payload["run"])

    def test_payload_is_json_serializable_without_float_financial_values(self) -> None:
        payload = run_dashboard_case(build_default_case())
        encoded = json.dumps(payload)
        self.assertIn('"forecast_shortfall": "785151.', encoded)
        self.assertNotIsInstance(payload["summary"]["forecast_shortfall"], float)

    def test_invalid_payload_reports_missing_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing case fields"):
            case_from_payload({"aircraft_type": "Narrowbody"})

    def test_editable_case_run_changes_results_and_is_stored(self) -> None:
        case_payload = build_default_case().to_dict()
        case_payload["default_monthly_fh"] = "300"
        store = DashboardRunStore()
        result = store.create(case_payload)
        run_id = result["run"]["run_id"]
        self.assertEqual(store.get(run_id), result)
        self.assertFalse(result["run"]["demo_case"])
        self.assertNotEqual(
            result["summary"]["forecast_reserve_inflow"],
            "9168903.188051829105809911610",
        )


class DashboardFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.static_root = Path(__file__).resolve().parents[1] / "dashboard" / "static"

    def test_dashboard_has_all_stage_views_and_editable_workflow(self) -> None:
        html = (self.static_root / "index.html").read_text(encoding="utf-8")
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        for view in (
            "overview",
            "assumptions",
            "utilization",
            "events",
            "inflows",
            "cashflow",
            "risk",
            "audit",
        ):
            self.assertIn(f'data-view="{view}"', html)
        self.assertIn('fetch("/api/runs"', script)
        self.assertIn("data-case-field", script)
        self.assertIn("data-component-field", script)
        self.assertIn("utilization_overrides", script)

    def test_dashboard_runtime_assets_are_self_contained(self) -> None:
        for filename in (
            "index.html",
            "styles.css",
            "app.js",
            "dashboard-data.js",
            "demo-payload.json",
        ):
            path = self.static_root / filename
            self.assertTrue(path.is_file(), filename)
            self.assertGreater(path.stat().st_size, 100)

    def test_embedded_startup_payload_contains_every_dashboard_section(self) -> None:
        payload = json.loads(
            (self.static_root / "dashboard-data.json").read_text(encoding="utf-8")
        )
        for section in (
            "run",
            "case",
            "summary",
            "utilization",
            "maintenance_calendar",
            "reserve_inflows",
            "opening_balance_history",
            "historical_funding_events",
            "cashflows",
            "funding_events",
            "audit",
        ):
            self.assertIn(section, payload)
        self.assertEqual(len(payload["case"]["components"]), 5)

    def test_inputs_group_reserve_rates_with_lease_terms(self) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        styles = (self.static_root / "styles.css").read_text(encoding="utf-8")
        for section in (
            "Aircraft Description",
            "Aircraft Maintenance Program Information",
            "Aircraft Lease Terms",
            "Maintenance Reserve Terms",
        ):
            self.assertIn(section, script)
        self.assertNotIn("RAW DATA · Section 4", script)
        self.assertIn("Contractual inputs", script)
        self.assertNotIn("Automation controls", script)
        self.assertNotIn("Historical event and escalation anchors", script)
        self.assertIn("data-sync-engine", script)
        self.assertIn("manufacture-year values", script)
        self.assertIn("lease-commencement rates", script)
        self.assertIn("applyV1DerivedBaseDates", script)
        self.assertIn("percentInput", script)
        self.assertNotIn("Number(component.annual_cost_escalation) * 100", script)
        self.assertNotIn("Number(component.annual_reserve_escalation) * 100", script)
        self.assertNotIn("Cost basis year", script)
        self.assertNotIn("Rate effective date", script)
        self.assertIn("Readability scale", styles)
        html = (self.static_root / "index.html").read_text(encoding="utf-8")
        self.assertIn("Aircraft Maintenance Cash Flow Analysis", html)
        self.assertIn("Inputs &amp; Assumptions", html)
        self.assertIn("Reference model (V1)", html)
        self.assertIn('href="v2/"', html)
        self.assertIn("Lifecycle scenarios", html)
        self.assertIn("Reference case", html)
        self.assertIn("Calculation workflow", html)
        self.assertIn("Risk &amp; assurance", html)
        self.assertIn("V2-aligned reference workspace shell", styles)
        self.assertNotIn("Case Setup", html)

    def test_utilization_prioritizes_exercise_schedule_over_redundant_chart(self) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        styles = (self.static_root / "styles.css").read_text(encoding="utf-8")
        self.assertNotIn("Monthly profile", script)
        self.assertNotIn('class="utilization-chart"', script)
        self.assertIn("Stage 1 output", script)
        self.assertIn("Forecast utilization schedule", script)
        self.assertIn("Calculation basis", script)
        self.assertIn("Manufacture date", script)
        self.assertIn("Utilization checkpoints", script)
        self.assertIn("Cumulative since manufacture", script)
        self.assertIn("Historic / future assumption", script)
        self.assertNotIn("Contract utilization assumption", script)
        self.assertIn('class="schedule-actions"', script)
        self.assertIn('<col class="period-column">', script)
        self.assertIn(".utilization-table table", styles)
        self.assertIn("max-height: none", styles)
        self.assertIn("overflow: visible", styles)
        self.assertIn("Analysis date", script)
        self.assertIn("Lease expiry", script)

    def test_maintenance_events_separates_basis_outputs_and_schedule(self) -> None:
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        styles = (self.static_root / "styles.css").read_text(encoding="utf-8")
        self.assertIn("Maintenance intervals used", script)
        self.assertIn("Forecast event summary", script)
        self.assertIn("Scheduled event months", script)
        self.assertIn("Stage 2 output", script)
        self.assertIn("Maintenance calendar schedule", script)
        self.assertIn('data-export="maintenance_calendar"', script)
        self.assertIn('"event-schedule-table"', script)
        self.assertIn(".event-schedule-table", styles)
        self.assertIn("max-height: none", styles)

    def test_reserve_workflow_prioritizes_event_settlement_over_detail(self) -> None:
        html = (self.static_root / "index.html").read_text(encoding="utf-8")
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        styles = (self.static_root / "styles.css").read_text(encoding="utf-8")
        self.assertIn('data-view="inflows"', html)
        self.assertIn("Maintenance reserve inflow", script)
        self.assertIn("Stage 3 output", script)
        self.assertIn("Core decision table", script)
        self.assertIn("Opening balance bridge", script)
        self.assertIn("Historical reserve inflow", script)
        self.assertIn("Analysis-date opening balance", script)
        self.assertIn("Historical event settlements", script)
        self.assertIn("Component reserve available", script)
        self.assertIn("Component outflow", script)
        self.assertIn("Component closing balance", script)
        self.assertIn("Component accounts are segregated", script)
        self.assertIn("Select the account to trace", script)
        self.assertIn("All component accounts", script)
        self.assertIn('aria-label="Select reserve account"', script)
        self.assertLess(script.index("Opening balance bridge"), script.index("Core decision table"))
        self.assertIn("historical roll-forward", script)
        self.assertIn("Forecast event settlement", script)
        self.assertIn("Component account reconciliation", script)
        self.assertIn("Portfolio total balance path", script)
        self.assertIn("Outflow is the lower of event cost and that component’s reserve available", script)
        self.assertLess(script.index("Core decision table"), script.index("Stage 4 calculation detail"))
        self.assertIn("Supporting calculation detail", script)
        self.assertIn(".historical-settlement-table", styles)
        self.assertIn(".reserve-account-control", styles)
        self.assertIn(".reserve-account-tabs", styles)
        self.assertIn(".settlement-table", styles)
        self.assertIn(".component-account-table", styles)
        self.assertIn(".cashflow-detail-table", styles)

    def test_reserve_adequacy_prioritizes_filtered_funding_exceptions(self) -> None:
        html = (self.static_root / "index.html").read_text(encoding="utf-8")
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        styles = (self.static_root / "styles.css").read_text(encoding="utf-8")
        self.assertIn("Reserve Adequacy", html)
        self.assertIn("Forecast maintenance reserve adequacy", script)
        self.assertIn("Select the account to assess", script)
        self.assertIn("const riskEvents = events.filter", script)
        self.assertIn("Total shortfall", script)
        self.assertIn("Lowest coverage", script)
        self.assertNotIn("Average coverage", script)
        self.assertIn("Exceptions requiring attention", script)
        self.assertIn("Underfunded maintenance events", script)
        self.assertIn("Funding action required", script)
        self.assertIn("All event funding outcomes", script)
        self.assertIn("Post-event reserve", script)
        self.assertIn(".risk-exception-grid", styles)
        self.assertIn(".funding-gap", styles)

    def test_model_validation_uses_dynamic_checks_and_regression_evidence(self) -> None:
        html = (self.static_root / "index.html").read_text(encoding="utf-8")
        script = (self.static_root / "app.js").read_text(encoding="utf-8")
        styles = (self.static_root / "styles.css").read_text(encoding="utf-8")
        self.assertIn("Model Validation", html)
        self.assertIn("Model assurance & reconciliation", script)
        self.assertIn("Run identity", script)
        self.assertIn("Deterministic Python engine", script)
        self.assertIn("Historical and forecast calculation checks", script)
        self.assertIn("Demonstration outputs matched", script)
        self.assertIn("Changes from default demo", script)
        self.assertIn("data-export-validation", script)
        self.assertNotIn("555 passed", script)
        self.assertIn(".validation-check-list", styles)
        self.assertIn(".workbook-reconciliation", styles)


class DashboardAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.server = create_server(port=0)
        except PermissionError as exc:
            raise unittest.SkipTest(
                "local socket binding is unavailable in this execution environment"
            ) from exc
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request_json(self, path: str, *, method: str = "GET", payload: object | None = None) -> tuple[int, dict[str, object]]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_health_and_demo_case_endpoints(self) -> None:
        status, health = self.request_json("/api/health")
        case_status, demo = self.request_json("/api/cases/demo")
        self.assertEqual(status, 200)
        self.assertEqual(health["calculation_scope"], [1, 2, 3, 4])
        self.assertEqual(case_status, 200)
        self.assertEqual(demo["case"]["aircraft_type"], "A320-200")

    def test_run_and_section_endpoints(self) -> None:
        status, run = self.request_json("/api/runs", method="POST", payload={})
        self.assertEqual(status, 201)
        run_id = run["run"]["run_id"]
        section_status, section = self.request_json(f"/api/runs/{run_id}/funding-risk")
        self.assertEqual(section_status, 200)
        self.assertEqual(len(section["funding_events"]), 5)

    def test_invalid_run_returns_structured_error(self) -> None:
        status, error = self.request_json(
            "/api/runs", method="POST", payload={"case": {"aircraft_type": "Narrowbody"}}
        )
        self.assertEqual(status, 400)
        self.assertEqual(error["error"], "invalid_case_inputs")


if __name__ == "__main__":
    unittest.main()
