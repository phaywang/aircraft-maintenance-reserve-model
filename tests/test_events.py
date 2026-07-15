from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd

from aircraft_cashflow.config import build_default_case
from aircraft_cashflow.events import (
    build_forecast_maintenance_calendar,
    build_full_maintenance_calendar,
    event_count_column,
    event_flag_column,
)
from aircraft_cashflow.export import write_maintenance_calendar_csv
from aircraft_cashflow.models import UtilizationOverride


class MaintenanceCalendarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = build_default_case()

    def test_demo_forecast_event_months(self) -> None:
        frame = build_forecast_maintenance_calendar(self.case)
        events = frame.loc[frame["mx_calendar"] != "-", ["date", "mx_calendar"]]
        self.assertEqual(
            list(events.itertuples(index=False, name=None)),
            [
                (date(2027, 2, 28), "E1,E2"),
                (date(2028, 11, 30), "LDG"),
                (date(2029, 6, 30), "6Y,12Y"),
            ],
        )

    def test_demo_full_history_contains_prior_events(self) -> None:
        frame = build_full_maintenance_calendar(self.case).set_index("date")
        self.assertEqual(frame.loc[date(2022, 4, 30), "mx_calendar"], "E1,E2")
        self.assertEqual(frame.loc[date(2023, 6, 30), "mx_calendar"], "6Y")

    def test_component_flags_and_counts_are_separate(self) -> None:
        frame = build_forecast_maintenance_calendar(self.case).set_index("date")
        engine_date = date(2027, 2, 28)
        self.assertTrue(frame.loc[engine_date, event_flag_column("E1")])
        self.assertTrue(frame.loc[engine_date, event_flag_column("E2")])
        self.assertEqual(frame.loc[engine_date, event_count_column("E1")], 1)
        self.assertEqual(frame.loc[engine_date, event_count_column("E2")], 1)
        self.assertFalse(frame.loc[engine_date, event_flag_column("LDG")])

    def test_threshold_crossing_detects_event_when_usage_skips_exact_multiple(self) -> None:
        override = UtilizationOverride(date(2027, 2, 28), 400, 95)
        case = replace(self.case, utilization_overrides=(override,))
        frame = build_forecast_maintenance_calendar(case).set_index("date")
        event_date = date(2027, 2, 28)
        self.assertEqual(frame.loc[event_date, "ttsn"], 30300)
        self.assertTrue(frame.loc[event_date, event_flag_column("E1")])
        self.assertEqual(frame.loc[event_date, "mx_calendar"], "E1,E2")

    def test_event_count_records_multiple_thresholds_crossed_in_one_month(self) -> None:
        override = UtilizationOverride(date(2027, 2, 28), 30500, 95)
        case = replace(self.case, utilization_overrides=(override,))
        frame = build_forecast_maintenance_calendar(case).set_index("date")
        event_date = date(2027, 2, 28)
        self.assertEqual(frame.loc[event_date, event_count_column("E1")], 3)
        self.assertEqual(frame.loc[event_date, event_count_column("E2")], 3)
        self.assertEqual(frame.loc[event_date, "mx_calendar"], "E1,E2")

    def test_e1_and_e2_can_have_different_intervals(self) -> None:
        components = tuple(
            replace(component, interval=14000) if component.code == "E2" else component
            for component in self.case.components
        )
        case = replace(self.case, components=components)
        frame = build_forecast_maintenance_calendar(case).set_index("date")
        self.assertTrue(frame.loc[date(2026, 6, 30), event_flag_column("E2")])
        self.assertFalse(frame.loc[date(2026, 6, 30), event_flag_column("E1")])
        self.assertTrue(frame.loc[date(2027, 2, 28), event_flag_column("E1")])

    def test_utilization_change_does_not_move_calendar_events(self) -> None:
        case = replace(self.case, default_monthly_fh=100, default_monthly_fc=50)
        frame = build_forecast_maintenance_calendar(case).set_index("date")
        self.assertEqual(frame.loc[date(2029, 6, 30), "mx_calendar"], "6Y,12Y")

    def test_step2_csv_is_inspectable(self) -> None:
        frame = build_forecast_maintenance_calendar(self.case)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_maintenance_calendar_csv(
                frame, Path(temp_dir) / "step2.csv"
            )
            loaded = pd.read_csv(path)
        self.assertEqual(len(loaded), 37)
        self.assertIn("mx_calendar", loaded.columns)
        self.assertIn(event_flag_column("E1"), loaded.columns)


if __name__ == "__main__":
    unittest.main()
