"""Month-end date helpers used by the deterministic calculation timeline."""

from __future__ import annotations

import calendar
from datetime import date, timedelta


def is_month_end(value: date) -> bool:
    """Return True when value is the final calendar day of its month."""

    return (value + timedelta(days=1)).month != value.month


def add_months_eom(value: date, months: int) -> date:
    """Shift a date by whole months and return the target month-end."""

    if not isinstance(months, int):
        raise TypeError("months must be an integer")
    month_index = value.year * 12 + (value.month - 1) + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


def month_end_range(start: date, end: date) -> list[date]:
    """Return an inclusive sequence of month-end dates."""

    if start > end:
        raise ValueError("start date must not be after end date")
    if not is_month_end(start) or not is_month_end(end):
        raise ValueError("timeline start and end dates must be month-end dates")

    result: list[date] = []
    current = start
    while current <= end:
        result.append(current)
        current = add_months_eom(current, 1)
    return result


def completed_months(start: date, end: date) -> int:
    """Return the number of whole month-end steps between two dates."""

    if start > end:
        raise ValueError("start date must not be after end date")
    if not is_month_end(start) or not is_month_end(end):
        raise ValueError("completed-month calculation requires month-end dates")
    return (end.year - start.year) * 12 + end.month - start.month

