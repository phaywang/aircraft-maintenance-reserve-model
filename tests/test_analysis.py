"""V2.7 deterministic conclusion and LLM boundary tests."""

from __future__ import annotations

import json
import unittest
from decimal import Decimal

from aircraft_cashflow.analysis import (
    build_decision_analysis, build_llm_explanation_payload,
)
from aircraft_cashflow.v2_demo import V2_COMMON_HORIZON, build_v2_demo_alternatives
from aircraft_cashflow.valuation import compare_alternatives


class DecisionAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.alternatives = build_v2_demo_alternatives()
        cls.valuation = compare_alternatives(
            cls.alternatives, "0.09", "30-month", V2_COMMON_HORIZON
        )
        cls.analysis = build_decision_analysis(cls.alternatives, cls.valuation)

    def test_recommendation_is_highest_npv_alternative(self) -> None:
        highest = max(
            self.valuation.summary.to_dict("records"),
            key=lambda row: Decimal(str(row["npv"])),
        )
        self.assertEqual(
            self.analysis.recommended_alternative_id,
            highest["alternative_id"],
        )
        self.assertEqual(self.analysis.recommendation_basis, "highest_common_horizon_npv")
        self.assertGreater(self.analysis.npv_lead, 0)

    def test_diagnostics_rank_and_reconcile(self) -> None:
        self.assertEqual([item.rank for item in self.analysis.alternatives], [1, 2])
        self.assertEqual(
            self.analysis.npv_lead,
            self.analysis.alternatives[0].npv - self.analysis.alternatives[1].npv,
        )
        self.assertTrue(all(item.total_unfunded_exposure >= 0 for item in self.analysis.alternatives))

    def test_query_cannot_change_deterministic_analysis(self) -> None:
        first = build_llm_explanation_payload(
            self.alternatives, self.valuation, self.analysis, "Explain value."
        )
        second = build_llm_explanation_payload(
            self.alternatives, self.valuation, self.analysis, "Focus on maintenance."
        )
        self.assertNotEqual(first["query"], second["query"])
        self.assertEqual(first["deterministic_analysis"], second["deterministic_analysis"])
        self.assertFalse(first["guardrails"]["may_change_numbers"])
        self.assertFalse(first["guardrails"]["may_change_ranking"])

    def test_explanation_payload_is_json_serializable_after_dashboard_serialization(self) -> None:
        from aircraft_cashflow.v2_dashboard_service import build_v2_dashboard_payload

        payload = build_v2_dashboard_payload()["llm_explanation_payload"]
        encoded = json.dumps(payload)
        self.assertIn("explain_deterministic_aircraft_lifecycle_results", encoded)
        self.assertEqual(payload["comparison"]["common_horizon"], "2033-12-31")

    def test_blank_query_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be blank"):
            build_llm_explanation_payload(
                self.alternatives, self.valuation, self.analysis, "  "
            )


if __name__ == "__main__":
    unittest.main()
