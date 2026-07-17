from __future__ import annotations

import unittest
from pathlib import Path

from aircraft_cashflow.llm.analysis_packet import (
    build_comparison_analysis_packet,
    build_scenario_analysis_packet,
    build_v1_analysis_packet,
    build_v1_case_questions_packet,
)
from aircraft_cashflow.case_questions import calculate_next_engine_interval_sensitivity
from aircraft_cashflow.config import build_default_case
from aircraft_cashflow.dashboard_service import run_dashboard_case
from aircraft_cashflow.llm.bedrock_client import TextInvokeResult, resolve_aws_params
from aircraft_cashflow.llm.guardrails import numeric_guardrail_check
from aircraft_cashflow.llm.prompts import SYSTEM_PROMPT, build_report_prompt
from aircraft_cashflow.llm.report_service import (
    generate_analysis_answer,
    generate_analysis_report,
    generate_v1_analysis,
    generate_v1_case_questions_report,
)
from aircraft_cashflow.scenario_builder import build_scenario_payload, default_scenario_input


class AnalysisPacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = build_scenario_payload()
        cls.packet = build_scenario_analysis_packet(cls.result)

    def test_packet_is_lessor_focused_and_carries_verified_event_claims(self) -> None:
        self.assertEqual(self.packet["perspective"], "lessor")
        self.assertEqual(self.packet["report_scope"], "current_scenario")
        self.assertGreater(len(self.packet["verified_claims"]), 20)
        self.assertEqual(len(self.packet["events"]), len(self.result["events"]))
        self.assertTrue(all(
            claim["status"] == "verified" and claim["display"]
            for claim in self.packet["verified_claims"]
        ))
        net_claim = next(
            claim for claim in self.packet["verified_claims"]
            if claim["claim_id"].endswith("net_reserve_cash_movement")
        )
        self.assertTrue(net_claim["display"].startswith("-$"))
        self.assertIn("maintenance_program", self.packet)
        self.assertIn("utilization_regimes", self.packet["scenario"])
        self.assertTrue(self.packet["scenario"]["leases"][0]["reserve_accounts"])
        lease_rate_claim = next(
            claim for claim in self.packet["verified_claims"]
            if ":lease:" in claim["claim_id"] and ":rate:" in claim["claim_id"]
        )
        self.assertEqual(lease_rate_claim["unit"], "currency")

    def test_comparison_packet_accepts_more_than_two_scenarios(self) -> None:
        packet = build_comparison_analysis_packet([self.result, self.result, self.result])
        self.assertEqual(packet["scenario_count"], 3)
        self.assertIn("Do not rank", packet["comparison_rule"])

    def test_prompt_is_english_and_preserves_excluded_scope(self) -> None:
        prompt = build_report_prompt(self.packet, "current_scenario")
        self.assertIn("Current Scenario Analysis", prompt)
        self.assertIn("time value of money", prompt)
        self.assertIn("professional English", SYSTEM_PROMPT)
        self.assertNotRegex(prompt, r"[\u4e00-\u9fff]")


class NumericGuardrailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.claims = [{
            "claim_id": "scenario:base:summary:cost",
            "status": "verified",
            "display": "$1,000.00",
        }, {
            "claim_id": "scenario:base:summary:coverage",
            "status": "verified",
            "display": "63.8%",
        }]

    def test_exact_same_line_values_pass(self) -> None:
        report = (
            "Cost is $1,000.00 [verified: scenario:base:summary:cost].\n"
            "Coverage is 63.8% [verified: scenario:base:summary:coverage]."
        )
        checked = numeric_guardrail_check(report, self.claims)
        self.assertEqual(checked["status"], "pass")
        self.assertEqual(checked["financial_numbers_checked"], 2)

    def test_wrong_value_with_valid_tag_is_blocked(self) -> None:
        checked = numeric_guardrail_check(
            "Cost is $999.00 [verified: scenario:base:summary:cost].", self.claims
        )
        self.assertEqual(checked["status"], "block")
        self.assertEqual(checked["blocked_count"], 1)

    def test_unknown_verified_tag_is_blocked(self) -> None:
        checked = numeric_guardrail_check(
            "No financial figure. [verified: invented:claim]", self.claims
        )
        self.assertEqual(checked["status"], "block")
        self.assertEqual(checked["unknown_verified_tags"], ["invented:claim"])


class ReportServiceTests(unittest.TestCase):
    def test_current_scenario_report_uses_injected_bedrock_invoker(self) -> None:
        calls = []

        def fake_invoke(prompt: str, **kwargs: object) -> TextInvokeResult:
            calls.append((prompt, kwargs))
            return TextInvokeResult(
                text="# Current Scenario Analysis\n\nNo unsupported financial figures.",
                stop_reason="end_turn",
                model_id="test-model",
            )

        result = generate_analysis_report(
            "current_scenario", [default_scenario_input()], invoke=fake_invoke
        )
        self.assertEqual(result["guardrail_status"], "pass")
        self.assertEqual(result["language"], "en")
        self.assertEqual(result["model_id"], "test-model")
        self.assertEqual(len(calls), 1)

    def test_guardrail_triggers_one_repair_attempt(self) -> None:
        responses = iter([
            "$999.00 without a verified source.",
            "# Current Scenario Analysis\n\nCorrected qualitative assessment.",
        ])

        def fake_invoke(prompt: str, **kwargs: object) -> TextInvokeResult:
            return TextInvokeResult(
                text=next(responses), stop_reason="end_turn", model_id="test-model"
            )

        result = generate_analysis_report(
            "current_scenario", [default_scenario_input()], invoke=fake_invoke
        )
        self.assertEqual(result["guardrail_status"], "repaired")

    def test_persistently_unverified_lines_are_removed_before_publication(self) -> None:
        def fake_invoke(prompt: str, **kwargs: object) -> TextInvokeResult:
            return TextInvokeResult(
                text=(
                    "# Current Scenario Analysis\n\n"
                    "This qualitative conclusion remains supported by the model.\n\n"
                    "Unsupported estimate is $9.9M."
                ),
                stop_reason="end_turn",
                model_id="test-model",
            )

        result = generate_analysis_report(
            "current_scenario", [default_scenario_input()], invoke=fake_invoke
        )
        self.assertEqual(result["guardrail_status"], "repaired")
        self.assertEqual(result["removed_line_count"], 1)
        self.assertNotIn("$9.9M", result["report_markdown"])

    def test_v2_current_scenario_question_uses_verified_packet(self) -> None:
        calls = []

        def fake_invoke(prompt: str, **kwargs: object) -> TextInvokeResult:
            calls.append(prompt)
            return TextInvokeResult(
                text="# Analysis Answer\n\nQualitative lifecycle answer.",
                stop_reason="end_turn",
                model_id="test-model",
            )

        question = "Which lease creates the largest funding exposure?"
        result = generate_analysis_answer(
            "current_scenario", [default_scenario_input()], question,
            invoke=fake_invoke,
        )
        self.assertEqual(result["mode"], "question")
        self.assertEqual(result["analysis_scope"], "current_scenario")
        self.assertEqual(result["question"], question)
        self.assertIn(question, calls[0])
        self.assertIn("must be edited and rerun", calls[0])

    def test_v2_cross_scenario_question_requires_two_scenarios(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least two"):
            generate_analysis_answer(
                "cross_scenario", [default_scenario_input()], "Compare funding."
            )

    def test_v1_case_report_uses_question_led_english_prompt(self) -> None:
        calls = []

        def fake_invoke(prompt: str, **kwargs: object) -> TextInvokeResult:
            calls.append(prompt)
            return TextInvokeResult(
                text="# Maintenance Reserve Analysis\n\nQualitative verified response.",
                stop_reason="end_turn",
                model_id="test-model",
            )

        result = generate_v1_case_questions_report(
            build_default_case().to_dict(), invoke=fake_invoke
        )
        self.assertEqual(result["report_type"], "v1_case_questions")
        self.assertEqual(result["language"], "en")
        self.assertIn("Question 1 — Unfunded Maintenance Expenditure", calls[0])
        self.assertIn("Question 3 — Engine Interval Sensitivity", calls[0])
        self.assertIn("| Lower interval |", result["report_markdown"])
        self.assertIn("| Base |", result["report_markdown"])
        self.assertIn("| Higher interval |", result["report_markdown"])
        self.assertIn(
            "[verified: v1:sensitivity:interval_change]",
            result["report_markdown"],
        )

    def test_v1_general_report_uses_current_run_evidence(self) -> None:
        calls = []

        def fake_invoke(prompt: str, **kwargs: object) -> TextInvokeResult:
            calls.append(prompt)
            return TextInvokeResult(
                text="# Maintenance Reserve Analysis\n\nQualitative assessment.",
                stop_reason="end_turn",
                model_id="test-model",
            )

        result = generate_v1_analysis(
            build_default_case().to_dict(), mode="report",
            report_type="full_analysis", invoke=fake_invoke,
        )
        self.assertEqual(result["mode"], "report")
        self.assertEqual(result["report_type"], "full_analysis")
        self.assertIn("v1_current_run_analysis", calls[0])
        self.assertNotIn("original recruitment", calls[0].lower())
        self.assertIn("## Engine Interval Sensitivity", result["report_markdown"])

    def test_v1_custom_question_is_preserved_and_scope_guarded(self) -> None:
        calls = []

        def fake_invoke(prompt: str, **kwargs: object) -> TextInvokeResult:
            calls.append(prompt)
            return TextInvokeResult(
                text="# Analysis Answer\n\nThe current run supports a qualitative answer.",
                stop_reason="end_turn",
                model_id="test-model",
            )

        question = "Which component accounts should the lessor review first?"
        result = generate_v1_analysis(
            build_default_case().to_dict(), mode="question", question=question,
            invoke=fake_invoke,
        )
        self.assertEqual(result["mode"], "question")
        self.assertEqual(result["question"], question)
        self.assertIn(question, calls[0])
        self.assertIn("must be updated and rerun", calls[0])

    def test_aws_defaults_match_reference_project_pattern(self) -> None:
        _, region, model = resolve_aws_params(profile="", region="us-east-1")
        self.assertEqual(region, "us-east-1")
        self.assertEqual(model, "us.anthropic.claude-sonnet-4-6")


class AnalysisDashboardContractTests(unittest.TestCase):
    def test_v1_exposes_general_analysis_and_qa_workspace(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "dashboard/static/index.html").read_text(encoding="utf-8")
        script = (root / "dashboard/static/app.js").read_text(encoding="utf-8")
        styles = (root / "dashboard/static/styles.css").read_text(encoding="utf-8")
        self.assertIn('data-view="analysis"', html)
        self.assertIn("Analysis &amp; Q&amp;A", html)
        self.assertIn("How to use this workspace", script)
        self.assertIn("Generate report", script)
        self.assertIn('safe.startsWith("### ")', script)
        self.assertIn("Ask about the current model results", script)
        self.assertIn('fetch("/api/v1/analysis"', script)
        self.assertIn("The language model does not create new cash-flow results", script)
        self.assertIn(".analysis-usage-guide", styles)
        self.assertIn(".analysis-question-field", styles)
        self.assertIn(".verified-ref", styles)

    def test_hosted_assets_match_local_v1_assets(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for name in ("index.html", "app.js", "styles.css"):
            self.assertEqual(
                (root / "dashboard/static" / name).read_bytes(),
                (root / "docs" / name).read_bytes(),
            )

    def test_v2_exposes_separate_advisory_report_workspace(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "dashboard/v2/index.html").read_text(encoding="utf-8")
        script = (root / "dashboard/v2/app.js").read_text(encoding="utf-8")
        styles = (root / "dashboard/v2/styles.css").read_text(encoding="utf-8")
        self.assertIn("Analysis &amp; Q&amp;A", html)
        self.assertIn('data-view="report"', html)
        self.assertIn("Generate report", script)
        self.assertIn("How to use this workspace", script)
        self.assertIn("Ask about calculated lifecycle results", script)
        self.assertIn("data-analysis-question", script)
        self.assertIn('fetch("/api/v2/analysis"', script)
        self.assertIn("Bedrock does not calculate a new lifecycle forecast", script)
        self.assertIn(".verified-ref", styles)
        self.assertIn(".report-table", styles)
        self.assertIn(".analysis-usage-guide", styles)
        self.assertIn(".analysis-question-panel", styles)

    def test_hosted_assets_match_local_v2_assets(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for name in ("index.html", "app.js", "styles.css"):
            self.assertEqual(
                (root / "dashboard/v2" / name).read_bytes(),
                (root / "docs/v2" / name).read_bytes(),
            )


class V1CaseQuestionEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.case = build_default_case()
        cls.base = run_dashboard_case(cls.case)
        cls.sensitivity = calculate_next_engine_interval_sensitivity(
            cls.case, cls.base
        )
        cls.packet = build_v1_case_questions_packet(cls.base, cls.sensitivity)
        cls.analysis_packet = build_v1_analysis_packet(cls.base, cls.sensitivity)

    def test_general_packet_removes_recruitment_question_framing(self) -> None:
        self.assertEqual(
            self.analysis_packet["report_scope"], "v1_current_run_analysis"
        )
        self.assertNotIn("questions", self.analysis_packet)
        self.assertIn("analysis_capabilities", self.analysis_packet)
        self.assertEqual(len(self.analysis_packet["component_assumptions"]), 5)
        rate_claim = next(
            claim for claim in self.analysis_packet["verified_claims"]
            if claim["claim_id"] == "v1:assumption:E1:base_reserve_rate"
        )
        self.assertEqual(rate_claim["unit"], "currency")

    def test_packet_reproduces_the_three_original_case_questions(self) -> None:
        self.assertEqual(len(self.packet["questions"]), 3)
        self.assertIn("not be funded", self.packet["questions"][0]["text"])
        self.assertIn("fair or unfair", self.packet["questions"][1]["text"])
        self.assertIn("5% lower or 5% higher", self.packet["questions"][2]["text"])
        interval_claim = next(
            claim for claim in self.packet["verified_claims"]
            if claim["claim_id"] == "v1:sensitivity:interval_change"
        )
        self.assertEqual(interval_claim["display"], "5.0%")

    def test_engine_adjustment_can_be_cited_without_blocking_sensitivity_row(self) -> None:
        report = (
            "| Lower interval | 14,250 FH | 5.0% "
            "[verified: v1:sensitivity:interval_change] |"
        )
        checked = numeric_guardrail_check(report, self.packet["verified_claims"])
        self.assertEqual(checked["status"], "pass")

    def test_engine_sensitivity_freezes_history_and_moves_only_next_cycle(self) -> None:
        by_case = {item["case"]: item for item in self.sensitivity}
        self.assertEqual(by_case["lower_5pct"]["engine_interval_fh"], "14250.00")
        self.assertEqual(by_case["base"]["engine_interval_fh"], "15000")
        self.assertEqual(by_case["higher_5pct"]["engine_interval_fh"], "15750.00")
        self.assertEqual(by_case["lower_5pct"]["event_date"], "2026-11-30")
        self.assertEqual(by_case["base"]["event_date"], "2027-02-28")
        self.assertEqual(by_case["higher_5pct"]["event_date"], "2027-05-31")
        self.assertTrue(all(
            item["current_cycle_start_fh"] == "15000" for item in self.sensitivity
        ))

    def test_lower_interval_minimizes_next_event_lessor_reimbursement(self) -> None:
        by_case = {item["case"]: item for item in self.sensitivity}
        self.assertLess(
            float(by_case["lower_5pct"]["reimbursement"]),
            float(by_case["higher_5pct"]["reimbursement"]),
        )
        self.assertEqual(
            self.packet["questions"][2]["narrow_cashflow_result"], "lower_5pct"
        )


if __name__ == "__main__":
    unittest.main()
