"""Step 1: monthly aircraft utilization and cumulative usage."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from .dates import is_month_end, month_end_range
from .models import CaseInputs, UtilizationOverride


UTILIZATION_COLUMNS = (
    "date",
    "period",
    "fh_month",
    "fc_month",
    "ttsn",
    "tcsn",
)


def _validate_timeline_dates(case: CaseInputs) -> None:
    named_dates = {
        "date_of_manufacture": case.date_of_manufacture,
        "lease_start_date": case.lease_start_date,
        "analysis_date": case.analysis_date,
        "lease_expiry_date": case.lease_expiry_date,
    }
    invalid = [name for name, value in named_dates.items() if not is_month_end(value)]
    if invalid:
        raise ValueError(
            "V1 utilization timeline requires month-end dates: " + ", ".join(invalid)
        )


def _override_map(case: CaseInputs) -> dict[object, UtilizationOverride]:
    return {override.month_end: override for override in case.utilization_overrides}


def build_full_utilization(case: CaseInputs) -> pd.DataFrame:
    """Calculate usage from manufacture through lease expiry.

    The manufacture-date row is the zero-usage baseline. Each later month-end adds
    that row's monthly FH and FC to cumulative TTSN and TCSN. A nine-year interval
    therefore contains 108 completed monthly utilization periods.
    """

    _validate_timeline_dates(case)
    dates = month_end_range(case.date_of_manufacture, case.lease_expiry_date)
    overrides = _override_map(case)

    ttsn = Decimal("0")
    tcsn = Decimal("0")
    rows: list[dict[str, object]] = []

    for index, current_date in enumerate(dates):
        override = overrides.get(current_date)
        fh_month = (
            override.flight_hours if override is not None else case.default_monthly_fh
        )
        fc_month = (
            override.flight_cycles if override is not None else case.default_monthly_fc
        )

        if index == 0:
            fh_month = Decimal("0")
            fc_month = Decimal("0")

        if index > 0:
            ttsn += fh_month
            tcsn += fc_month

        rows.append(
            {
                "date": current_date,
                "period": index,
                "fh_month": fh_month,
                "fc_month": fc_month,
                "ttsn": ttsn,
                "tcsn": tcsn,
            }
        )

    return pd.DataFrame(rows, columns=UTILIZATION_COLUMNS)


def build_forecast_utilization(case: CaseInputs) -> pd.DataFrame:
    """Return the Step 1 table from analysis date through lease expiry."""

    full_timeline = build_full_utilization(case)
    forecast = full_timeline.loc[
        full_timeline["date"] >= case.analysis_date,
        ["date", "fh_month", "fc_month", "ttsn", "tcsn"],
    ].copy()
    forecast.insert(1, "period", range(len(forecast)))
    return forecast.loc[:, UTILIZATION_COLUMNS].reset_index(drop=True)
