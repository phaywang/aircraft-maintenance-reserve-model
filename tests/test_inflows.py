from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from aircraft_cashflow.config import build_default_case
from aircraft_cashflow.export import write_reserve_inflows_csv
from aircraft_cashflow.inflows import (
    build_forecast_reserve_inflows,
    build_full_reserve_inflows,
    reserve_inflow_column,
    reserve_rate_column,
)


class ReserveInflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = build_default_case()

    def test_demo_start_and_end_totals(self) -> None:
        frame = build_forecast_reserve_inflows(self.case).set_index("date")
        self.assertAlmostEqual(
            frame.loc[date(2026, 6, 30), "total_reserve_inflow"],
            Decimal("236637.3193847272898327168320"),
            places=8,
        )
        self.assertAlmostEqual(
            frame.loc[date(2029, 6, 30), "total_reserve_inflow"],
            Decimal("268334.1869590995192510063176"),
            places=8,
        )

    def test_january_escalation_is_constant_within_each_year(self) -> None:
        frame = build_forecast_reserve_inflows(self.case).set_index("date")
        dec_rate = frame.loc[date(2026, 12, 31), reserve_rate_column("6Y")]
        jan_rate = frame.loc[date(2027, 1, 31), reserve_rate_column("6Y")]
        oct_rate = frame.loc[date(2027, 10, 31), reserve_rate_column("6Y")]
        self.assertAlmostEqual(jan_rate, dec_rate * Decimal("1.028"), places=20)
        self.assertEqual(oct_rate, jan_rate)

    def test_reserve_bases_use_month_fh_and_fc(self) -> None:
        row = build_forecast_reserve_inflows(self.case).iloc[0]
        self.assertEqual(
            row[reserve_inflow_column("6Y")], row[reserve_rate_column("6Y")]
        )
        self.assertEqual(
            row[reserve_inflow_column("LDG")],
            row[reserve_rate_column("LDG")] * row["fc_month"],
        )
        self.assertEqual(
            row[reserve_inflow_column("E1")],
            row[reserve_rate_column("E1")] * row["fh_month"],
        )

    def test_utilization_change_only_affects_usage_based_reserves(self) -> None:
        changed = replace(self.case, default_monthly_fh=300, default_monthly_fc=120)
        base = build_forecast_reserve_inflows(self.case).iloc[0]
        scenario = build_forecast_reserve_inflows(changed).iloc[0]
        self.assertEqual(
            scenario[reserve_inflow_column("6Y")],
            base[reserve_inflow_column("6Y")],
        )
        self.assertEqual(
            scenario[reserve_inflow_column("12Y")],
            base[reserve_inflow_column("12Y")],
        )
        self.assertEqual(
            scenario[reserve_inflow_column("LDG")],
            base[reserve_inflow_column("LDG")] * Decimal("120") / Decimal("95"),
        )
        self.assertEqual(
            scenario[reserve_inflow_column("E1")],
            base[reserve_inflow_column("E1")] * Decimal("300") / Decimal("260"),
        )

    def test_reserve_collection_continues_after_event(self) -> None:
        frame = build_forecast_reserve_inflows(self.case).set_index("date")
        event_month = date(2027, 2, 28)
        following_month = date(2027, 3, 31)
        self.assertEqual(frame.loc[event_month, "mx_calendar"], "E1,E2")
        self.assertGreater(frame.loc[event_month, reserve_inflow_column("E1")], 0)
        self.assertEqual(
            frame.loc[event_month, reserve_inflow_column("E1")],
            frame.loc[following_month, reserve_inflow_column("E1")],
        )

    def test_reserve_collection_starts_after_lease_inception_not_manufacture(self) -> None:
        changed = replace(self.case, lease_start_date=date(2018, 6, 30))
        frame = build_full_reserve_inflows(changed).set_index("date")
        pre_lease = frame.loc[frame.index < changed.lease_start_date]
        self.assertTrue((pre_lease["total_reserve_inflow"] == Decimal("0")).all())
        self.assertEqual(
            frame.loc[changed.lease_start_date, "total_reserve_inflow"], Decimal("0")
        )
        self.assertGreater(
            frame.loc[date(2018, 7, 31), "total_reserve_inflow"], Decimal("0")
        )

    def test_total_equals_component_sum(self) -> None:
        frame = build_forecast_reserve_inflows(self.case)
        columns = [
            reserve_inflow_column(component.code)
            for component in self.case.components
        ]
        for row in frame.itertuples(index=False):
            expected = sum(
                (Decimal(str(getattr(row, column))) for column in columns),
                Decimal("0"),
            )
            self.assertEqual(row.total_reserve_inflow, expected)

    def test_step3_csv_is_inspectable(self) -> None:
        frame = build_forecast_reserve_inflows(self.case)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_reserve_inflows_csv(frame, Path(temp_dir) / "step3.csv")
            loaded = pd.read_csv(path)
        self.assertEqual(len(loaded), 37)
        self.assertIn(reserve_rate_column("E1"), loaded.columns)
        self.assertIn(reserve_inflow_column("E1"), loaded.columns)
        self.assertIn("total_reserve_inflow", loaded.columns)


if __name__ == "__main__":
    unittest.main()
