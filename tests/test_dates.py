from __future__ import annotations

import unittest
from datetime import date

from aircraft_cashflow.dates import add_months_eom, completed_months, month_end_range


class MonthEndDateTests(unittest.TestCase):
    def test_add_months_preserves_month_end(self) -> None:
        self.assertEqual(add_months_eom(date(2024, 1, 31), 1), date(2024, 2, 29))
        self.assertEqual(add_months_eom(date(2024, 2, 29), 1), date(2024, 3, 31))

    def test_month_end_range_is_inclusive(self) -> None:
        dates = month_end_range(date(2023, 10, 31), date(2024, 1, 31))
        self.assertEqual(
            dates,
            [
                date(2023, 10, 31),
                date(2023, 11, 30),
                date(2023, 12, 31),
                date(2024, 1, 31),
            ],
        )

    def test_completed_months_matches_reference_age(self) -> None:
        self.assertEqual(
            completed_months(date(2014, 10, 31), date(2023, 10, 31)), 108
        )

    def test_non_month_end_range_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "month-end"):
            month_end_range(date(2023, 10, 30), date(2024, 1, 31))


if __name__ == "__main__":
    unittest.main()

