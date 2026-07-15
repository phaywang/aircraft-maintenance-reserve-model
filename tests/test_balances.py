from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from aircraft_cashflow.balances import (
    available_balance_column,
    build_forecast_reserve_balances,
    build_full_reserve_balances,
    closing_balance_column,
    event_cost_column,
    opening_balance_column,
    reserve_outflow_column,
    unfunded_amount_column,
)
from aircraft_cashflow.config import build_default_case
from aircraft_cashflow.export import write_reserve_balances_csv
from aircraft_cashflow.inflows import reserve_inflow_column


class ReserveBalanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = build_default_case()

    def test_manufacture_baseline_has_no_inflow_or_balance(self) -> None:
        row = build_full_reserve_balances(self.case).iloc[0]
        self.assertEqual(row["date"], self.case.date_of_manufacture)
        self.assertEqual(row["total_reserve_inflow"], Decimal("0"))
        self.assertEqual(row["total_closing_balance"], Decimal("0"))

    def test_analysis_date_balances_are_generated_from_history(self) -> None:
        row = build_forecast_reserve_balances(self.case).iloc[0]
        expected = {
            "6Y": Decimal("487298.7909139040"),
            "12Y": Decimal("919599.7206475739"),
            "LDG": Decimal("411428.5595102887"),
            "E1": Decimal("4678909.2344278920"),
            "E2": Decimal("4678909.2344278920"),
        }
        for code, value in expected.items():
            self.assertAlmostEqual(row[closing_balance_column(code)], value, places=7)

    def test_demo_future_outflows_and_lease_end_balance(self) -> None:
        frame = build_forecast_reserve_balances(self.case).set_index("date")
        self.assertAlmostEqual(
            frame.loc[date(2027, 2, 28), "total_reserve_outflow"],
            Decimal("11014520.303579877"),
            places=7,
        )
        self.assertAlmostEqual(
            frame.loc[date(2028, 11, 30), "total_reserve_outflow"],
            Decimal("541709.4018852592"),
            places=7,
        )
        self.assertAlmostEqual(
            frame.loc[date(2029, 6, 30), "total_reserve_outflow"],
            Decimal("2297234.0748218643"),
            places=7,
        )
        self.assertAlmostEqual(
            frame.loc[date(2029, 6, 30), "total_closing_balance"],
            Decimal("6258742.935460652"),
            places=7,
        )

    def test_every_component_rollforward_ties(self) -> None:
        frame = build_full_reserve_balances(self.case)
        for row in frame.itertuples(index=False):
            for component in self.case.components:
                code = component.code
                opening = getattr(row, opening_balance_column(code))
                inflow = getattr(row, reserve_inflow_column(code))
                outflow = getattr(row, reserve_outflow_column(code))
                closing = getattr(row, closing_balance_column(code))
                self.assertEqual(closing, opening + inflow - outflow)

    def test_reimbursement_obeys_lower_of_rule(self) -> None:
        frame = build_full_reserve_balances(self.case)
        for row in frame.itertuples(index=False):
            for component in self.case.components:
                code = component.code
                outflow = getattr(row, reserve_outflow_column(code))
                self.assertLessEqual(outflow, getattr(row, available_balance_column(code)))
                self.assertLessEqual(outflow, getattr(row, event_cost_column(code)))
                self.assertGreaterEqual(outflow, Decimal("0"))
                self.assertGreaterEqual(getattr(row, closing_balance_column(code)), Decimal("0"))

    def test_six_year_event_does_not_trigger_twelve_year_outflow(self) -> None:
        frame = build_full_reserve_balances(self.case).set_index("date")
        event_date = date(2023, 6, 30)
        self.assertEqual(frame.loc[event_date, "mx_calendar"], "6Y")
        self.assertGreater(frame.loc[event_date, reserve_outflow_column("6Y")], 0)
        self.assertEqual(frame.loc[event_date, reserve_outflow_column("12Y")], 0)

    def test_historical_engine_shortfall_is_recorded(self) -> None:
        frame = build_full_reserve_balances(self.case).set_index("date")
        row = frame.loc[date(2022, 4, 30)]
        for code in ("E1", "E2"):
            self.assertGreater(row[unfunded_amount_column(code)], 0)
            self.assertEqual(row[closing_balance_column(code)], 0)

    def test_balance_changes_with_component_reserve_rate_not_hardcoded(self) -> None:
        components = tuple(
            replace(component, base_reserve_rate=Decimal("12000"))
            if component.code == "6Y"
            else component
            for component in self.case.components
        )
        changed_case = replace(self.case, components=components)
        base = build_forecast_reserve_balances(self.case).iloc[0]
        scenario = build_forecast_reserve_balances(changed_case).iloc[0]
        self.assertNotEqual(
            scenario[closing_balance_column("6Y")],
            base[closing_balance_column("6Y")],
        )
        self.assertEqual(
            scenario[closing_balance_column("12Y")],
            base[closing_balance_column("12Y")],
        )

    def test_non_event_month_has_zero_cost_outflow_and_shortfall(self) -> None:
        row = build_forecast_reserve_balances(self.case).set_index("date").loc[
            date(2027, 1, 31)
        ]
        for component in self.case.components:
            code = component.code
            self.assertEqual(row[event_cost_column(code)], 0)
            self.assertEqual(row[reserve_outflow_column(code)], 0)
            self.assertEqual(row[unfunded_amount_column(code)], 0)

    def test_expiry_month_collects_reserve_before_maintenance_settlement(self) -> None:
        row = build_forecast_reserve_balances(self.case).set_index("date").loc[
            self.case.lease_expiry_date
        ]
        self.assertEqual(row["mx_calendar"], "6Y,12Y")
        self.assertGreater(row["total_reserve_inflow"], 0)
        self.assertGreater(row["total_reserve_outflow"], 0)
        for code in ("6Y", "12Y"):
            self.assertEqual(
                row[available_balance_column(code)],
                row[opening_balance_column(code)] + row[reserve_inflow_column(code)],
            )

    def test_step4_csv_is_inspectable(self) -> None:
        frame = build_forecast_reserve_balances(self.case)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_reserve_balances_csv(frame, Path(temp_dir) / "step4.csv")
            loaded = pd.read_csv(path)
        self.assertEqual(len(loaded), 37)
        self.assertIn(reserve_outflow_column("E1"), loaded.columns)
        self.assertIn(closing_balance_column("E1"), loaded.columns)
        self.assertIn("total_unfunded_amount", loaded.columns)


if __name__ == "__main__":
    unittest.main()
