"""V2.1 dated utilization timeline for an aircraft lifecycle scenario."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from .lifecycle import (
    LeaseContract,
    Scenario,
    TransitionPeriod,
    UtilizationPattern,
    UtilizationRegime,
    lifecycle_segments,
)


LIFECYCLE_UTILIZATION_COLUMNS = (
    "date",
    "period",
    "start_date",
    "segment_id",
    "segment_type",
    "regime_id",
    "pattern",
    "actual",
    "input_source",
    "day_count",
    "days_in_month",
    "proration_factor",
    "flight_hours",
    "flight_cycles",
    "ttsn",
    "tcsn",
)


def _month_end(value: date) -> date:
    return date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])


def _segment_id(segment: LeaseContract | TransitionPeriod) -> str:
    return (
        segment.contract_id
        if isinstance(segment, LeaseContract)
        else segment.transition_id
    )


def _active_item(items: tuple[object, ...], current: date, start: str, end: str) -> object | None:
    return next(
        (
            item
            for item in items
            if getattr(item, start) <= current <= getattr(item, end)
        ),
        None,
    )


def _monthly_inputs(
    regime: UtilizationRegime, current: date
) -> tuple[Decimal, Decimal, str]:
    month_end = _month_end(current)
    override = next(
        (
            item
            for item in regime.month_overrides
            if item.month_end == month_end
        ),
        None,
    )
    if override is not None:
        return override.flight_hours, override.flight_cycles, "override"

    if regime.pattern is UtilizationPattern.EXPLICIT_MONTHS:
        raise ValueError(
            f"utilization regime {regime.regime_id!r} requires an explicit override "
            f"for {month_end.isoformat()}"
        )
    if regime.pattern is UtilizationPattern.SEASONAL_PROFILE:
        month_index = current.month - 1
        return (
            regime.monthly_fh * regime.seasonal_fh_factors[month_index],
            regime.monthly_fc * regime.seasonal_fc_factors[month_index],
            "seasonal_profile",
        )
    return regime.monthly_fh, regime.monthly_fc, "fixed_monthly"


def _empty_timeline() -> pd.DataFrame:
    return pd.DataFrame(columns=LIFECYCLE_UTILIZATION_COLUMNS)


def build_lifecycle_utilization(
    scenario: Scenario,
    through_date: date | None = None,
) -> pd.DataFrame:
    """Build the continuous V2 utilization timeline.

    Rows are split at calendar month, lifecycle-segment and utilization-regime
    boundaries. Monthly inputs are prorated by inclusive days in each slice.
    A known state, when supplied, is the authoritative opening TTSN/TCSN anchor;
    calculation then begins on the following day. Without one, cumulative usage
    starts at zero on the first modeled lifecycle day.
    """

    segments = tuple(lifecycle_segments(scenario))
    timeline_end = through_date or scenario.comparison_horizon
    if timeline_end > scenario.comparison_horizon:
        raise ValueError("through_date must not exceed comparison_horizon")

    first_date = segments[0].start_date
    ttsn = Decimal("0")
    tcsn = Decimal("0")
    current = first_date
    rows: list[dict[str, object]] = []

    if scenario.known_state is not None:
        state = scenario.known_state
        if state.as_of_date < first_date - timedelta(days=1):
            raise ValueError("known state cannot precede the modeled lifecycle")
        ttsn = state.ttsn
        tcsn = state.tcsn
        current = state.as_of_date + timedelta(days=1)
        anchor_segment = _active_item(
            segments, state.as_of_date, "start_date", "end_date"
        )
        rows.append(
            {
                "date": state.as_of_date,
                "period": 0,
                "start_date": state.as_of_date,
                "segment_id": (
                    _segment_id(anchor_segment) if anchor_segment is not None else None
                ),  # type: ignore[arg-type]
                "segment_type": "anchor",
                "regime_id": None,
                "pattern": None,
                "actual": True,
                "input_source": "known_state",
                "day_count": 0,
                "days_in_month": calendar.monthrange(
                    state.as_of_date.year, state.as_of_date.month
                )[1],
                "proration_factor": Decimal("0"),
                "flight_hours": Decimal("0"),
                "flight_cycles": Decimal("0"),
                "ttsn": ttsn,
                "tcsn": tcsn,
            }
        )

    if current > timeline_end:
        return pd.DataFrame(rows, columns=LIFECYCLE_UTILIZATION_COLUMNS)

    regimes = tuple(scenario.utilization_regimes)
    period = 1
    while current <= timeline_end:
        segment = _active_item(segments, current, "start_date", "end_date")
        if segment is None:
            raise ValueError(f"no lifecycle segment covers {current.isoformat()}")
        segment_id = _segment_id(segment)  # type: ignore[arg-type]
        eligible_regimes = tuple(
            regime for regime in regimes if regime.segment_id == segment_id
        )
        regime = _active_item(eligible_regimes, current, "start_date", "end_date")
        if regime is None:
            raise ValueError(
                f"no utilization regime covers {current.isoformat()} in segment "
                f"{segment_id!r}; add an explicit zero-flight regime for downtime"
            )
        regime = regime  # type: ignore[assignment]

        cutoff_boundary = (
            scenario.analysis_date
            if current <= scenario.analysis_date
            else timeline_end
        )
        slice_end = min(
            timeline_end,
            cutoff_boundary,
            segment.end_date,  # type: ignore[union-attr]
            regime.end_date,
            _month_end(current),
        )
        monthly_fh, monthly_fc, input_source = _monthly_inputs(regime, current)
        days_in_month = calendar.monthrange(current.year, current.month)[1]
        day_count = (slice_end - current).days + 1
        proration_factor = Decimal(day_count) / Decimal(days_in_month)
        flight_hours = monthly_fh * proration_factor
        flight_cycles = monthly_fc * proration_factor
        ttsn += flight_hours
        tcsn += flight_cycles

        rows.append(
            {
                "date": slice_end,
                "period": period,
                "start_date": current,
                "segment_id": segment_id,
                "segment_type": (
                    "lease" if isinstance(segment, LeaseContract) else "transition"
                ),
                "regime_id": regime.regime_id,
                "pattern": regime.pattern.value,
                "actual": regime.actual,
                "input_source": input_source,
                "day_count": day_count,
                "days_in_month": days_in_month,
                "proration_factor": proration_factor,
                "flight_hours": flight_hours,
                "flight_cycles": flight_cycles,
                "ttsn": ttsn,
                "tcsn": tcsn,
            }
        )
        period += 1
        current = slice_end + timedelta(days=1)

    return pd.DataFrame(rows, columns=LIFECYCLE_UTILIZATION_COLUMNS)


def build_forecast_lifecycle_utilization(scenario: Scenario) -> pd.DataFrame:
    """Return utilization rows on or after the selected analysis cut-off."""

    timeline = build_lifecycle_utilization(scenario)
    forecast = timeline.loc[timeline["date"] >= scenario.analysis_date].copy()
    if forecast.empty:
        return _empty_timeline()
    forecast["period"] = range(len(forecast))
    return forecast.loc[:, LIFECYCLE_UTILIZATION_COLUMNS].reset_index(drop=True)
