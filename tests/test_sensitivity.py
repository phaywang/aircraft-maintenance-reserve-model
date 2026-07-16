"""V2.8 sensitivity range and recommendation-switch tests."""

from __future__ import annotations

import unittest
from decimal import Decimal

from aircraft_cashflow.sensitivity import (
    SensitivitySpec, SensitivityVariable, run_sensitivity_analysis,
)
from aircraft_cashflow.v2_demo import V2_COMMON_HORIZON, build_v2_demo_alternatives


class SensitivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.alternatives = build_v2_demo_alternatives()
        cls.result = run_sensitivity_analysis(
            cls.alternatives, "0.09", "30-month", V2_COMMON_HORIZON
        )

    def test_default_grid_contains_base_and_low_high_cases(self) -> None:
        self.assertEqual(len(self.result.cases), 19)
        self.assertEqual(len(self.result.alternative_values), 38)
        self.assertEqual(self.result.base_recommendation_id, "30-month")
        self.assertEqual(self.result.cases.iloc[0]["case_id"], "base")

    def test_discontinuous_maintenance_timing_can_switch_recommendation(self) -> None:
        switched = set(
            self.result.cases.loc[
                self.result.cases["recommendation_changed"], "case_id"
            ]
        )
        self.assertIn("utilization-30:high", switched)
        self.assertIn("maintenance-42:low", switched)

    def test_driver_summary_reconciles_switch_counts(self) -> None:
        for driver in self.result.drivers.itertuples(index=False):
            cases = self.result.cases.loc[
                self.result.cases["sensitivity_id"] == driver.sensitivity_id
            ]
            self.assertEqual(
                driver.recommendation_switch_count,
                int(cases["recommendation_changed"].sum()),
            )
            self.assertLessEqual(driver.minimum_npv_gap, driver.maximum_npv_gap)

    def test_sensitivity_does_not_mutate_base_scenarios(self) -> None:
        before = self.alternatives.alternatives[0].scenario.to_dict()
        run_sensitivity_analysis(
            self.alternatives, "0.09", "30-month", V2_COMMON_HORIZON,
            (SensitivitySpec("rent", "Rent", SensitivityVariable.RENT, "0.9", "1.1", "30-month"),),
        )
        self.assertEqual(self.alternatives.alternatives[0].scenario.to_dict(), before)

    def test_invalid_sensitivity_range_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "nonnegative and ordered"):
            SensitivitySpec("bad", "Bad", SensitivityVariable.RENT, Decimal("1.2"), Decimal("0.8"))


if __name__ == "__main__":
    unittest.main()
