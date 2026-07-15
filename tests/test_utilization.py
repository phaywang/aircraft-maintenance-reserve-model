from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from aircraft_cashflow.config import build_default_case
from aircraft_cashflow.export import write_utilization_csv
from aircraft_cashflow.models import UtilizationOverride
from aircraft_cashflow.utilization import (
    UTILIZATION_COLUMNS,
    build_forecast_utilization,
    build_full_utilization,
)


class UtilizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = build_default_case()

    def test_demo_forecast_has_37_rows_and_periods_zero_to_36(self) -> None:
        frame = build_forecast_utilization(self.case)
        self.assertEqual(len(frame), 37)
        self.assertEqual(frame.iloc[0]["period"], 0)
        self.assertEqual(frame.iloc[-1]["period"], 36)
        self.assertEqual(tuple(frame.columns), UTILIZATION_COLUMNS)

    def test_demo_analysis_date_checkpoint(self) -> None:
        frame = build_forecast_utilization(self.case)
        row = frame.iloc[0]
        self.assertEqual(row["date"], date(2026, 6, 30))
        self.assertEqual(row["fh_month"], Decimal("260"))
        self.assertEqual(row["fc_month"], Decimal("95"))
        self.assertEqual(row["ttsn"], Decimal("28080"))
        self.assertEqual(row["tcsn"], Decimal("10260"))

    def test_demo_lease_expiry_checkpoint(self) -> None:
        frame = build_forecast_utilization(self.case)
        row = frame.iloc[-1]
        self.assertEqual(row["date"], date(2029, 6, 30))
        self.assertEqual(row["ttsn"], Decimal("37440"))
        self.assertEqual(row["tcsn"], Decimal("13680"))

    def test_full_timeline_uses_manufacture_date_as_zero_usage_baseline(self) -> None:
        frame = build_full_utilization(self.case)
        first = frame.iloc[0]
        second = frame.iloc[1]
        self.assertEqual(first["date"], date(2017, 6, 30))
        self.assertEqual(first["fh_month"], Decimal("0"))
        self.assertEqual(first["fc_month"], Decimal("0"))
        self.assertEqual(first["ttsn"], Decimal("0"))
        self.assertEqual(first["tcsn"], Decimal("0"))
        self.assertEqual(second["ttsn"], Decimal("260"))
        self.assertEqual(second["tcsn"], Decimal("95"))

    def test_month_override_updates_current_and_all_later_cumulative_usage(self) -> None:
        override = UtilizationOverride(date(2026, 7, 31), 300, 120)
        case = replace(self.case, utilization_overrides=(override,))
        frame = build_forecast_utilization(case).set_index("date")
        self.assertEqual(frame.loc[date(2026, 6, 30), "ttsn"], Decimal("28080"))
        self.assertEqual(frame.loc[date(2026, 7, 31), "fh_month"], Decimal("300"))
        self.assertEqual(frame.loc[date(2026, 7, 31), "ttsn"], Decimal("28380"))
        self.assertEqual(frame.loc[date(2026, 7, 31), "tcsn"], Decimal("10380"))
        self.assertEqual(frame.loc[date(2026, 8, 31), "ttsn"], Decimal("28640"))
        self.assertEqual(frame.loc[date(2026, 8, 31), "tcsn"], Decimal("10475"))

    def test_step1_csv_is_inspectable_and_preserves_rows(self) -> None:
        frame = build_forecast_utilization(self.case)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_utilization_csv(frame, Path(temp_dir) / "step1.csv")
            loaded = pd.read_csv(path)
        self.assertEqual(len(loaded), 37)
        self.assertEqual(tuple(loaded.columns), UTILIZATION_COLUMNS)
        self.assertEqual(loaded.iloc[0]["ttsn"], 28080)
        self.assertEqual(loaded.iloc[-1]["tcsn"], 13680)


if __name__ == "__main__":
    unittest.main()
