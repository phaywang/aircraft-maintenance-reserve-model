"""Typed inputs for the aircraft maintenance cash-flow model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any


class EventDriver(str, Enum):
    """Measurement that determines when a maintenance event occurs."""

    CALENDAR_MONTHS = "calendar_months"
    FLIGHT_HOURS = "flight_hours"
    FLIGHT_CYCLES = "flight_cycles"


class ReserveBasis(str, Enum):
    """Measurement used to charge a maintenance reserve."""

    PER_MONTH = "per_month"
    PER_FLIGHT_HOUR = "per_flight_hour"
    PER_FLIGHT_CYCLE = "per_flight_cycle"


def to_decimal(value: Decimal | int | float | str, field_name: str) -> Decimal:
    """Normalize a numeric input to Decimal without preserving float artifacts."""

    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric, not boolean")
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid number") from exc


def _require_nonnegative(name: str, value: Decimal) -> None:
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _is_month_end(value: date) -> bool:
    return (value + timedelta(days=1)).month != value.month


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


@dataclass(frozen=True)
class UtilizationOverride:
    """Optional FH/FC values that replace the case defaults for one month."""

    month_end: date
    flight_hours: Decimal | int | float | str
    flight_cycles: Decimal | int | float | str

    def __post_init__(self) -> None:
        flight_hours = to_decimal(self.flight_hours, "flight_hours")
        flight_cycles = to_decimal(self.flight_cycles, "flight_cycles")
        _require_nonnegative("flight_hours", flight_hours)
        _require_nonnegative("flight_cycles", flight_cycles)
        if not _is_month_end(self.month_end):
            raise ValueError("utilization override date must be a month-end date")
        object.__setattr__(self, "flight_hours", flight_hours)
        object.__setattr__(self, "flight_cycles", flight_cycles)


@dataclass(frozen=True)
class ComponentConfig:
    """Maintenance interval, cost, and reserve assumptions for one component."""

    code: str
    name: str
    event_driver: EventDriver
    interval: Decimal | int | float | str
    base_cost: Decimal | int | float | str
    cost_base_date: date
    annual_cost_escalation: Decimal | int | float | str
    reserve_basis: ReserveBasis
    base_reserve_rate: Decimal | int | float | str
    reserve_rate_base_date: date
    annual_reserve_escalation: Decimal | int | float | str
    last_event_date: date | None = None
    usage_since_event_at_lease_start: Decimal | int | float | str | None = None

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("component code must not be blank")
        if not self.name.strip():
            raise ValueError("component name must not be blank")
        if not isinstance(self.event_driver, EventDriver):
            raise ValueError("event_driver must be an EventDriver")
        if not isinstance(self.reserve_basis, ReserveBasis):
            raise ValueError("reserve_basis must be a ReserveBasis")

        interval = to_decimal(self.interval, "interval")
        base_cost = to_decimal(self.base_cost, "base_cost")
        cost_escalation = to_decimal(
            self.annual_cost_escalation, "annual_cost_escalation"
        )
        reserve_rate = to_decimal(self.base_reserve_rate, "base_reserve_rate")
        reserve_escalation = to_decimal(
            self.annual_reserve_escalation, "annual_reserve_escalation"
        )

        if interval <= 0:
            raise ValueError("interval must be greater than zero")
        _require_nonnegative("base_cost", base_cost)
        _require_nonnegative("annual_cost_escalation", cost_escalation)
        _require_nonnegative("base_reserve_rate", reserve_rate)
        _require_nonnegative("annual_reserve_escalation", reserve_escalation)

        usage_since_event = self.usage_since_event_at_lease_start
        if usage_since_event is not None:
            usage_since_event = to_decimal(
                usage_since_event, "usage_since_event_at_lease_start"
            )
            _require_nonnegative(
                "usage_since_event_at_lease_start", usage_since_event
            )
            if self.event_driver is EventDriver.CALENDAR_MONTHS:
                raise ValueError(
                    "calendar-driven components cannot use a usage-since-event input"
                )

        object.__setattr__(self, "interval", interval)
        object.__setattr__(self, "base_cost", base_cost)
        object.__setattr__(self, "annual_cost_escalation", cost_escalation)
        object.__setattr__(self, "base_reserve_rate", reserve_rate)
        object.__setattr__(
            self, "annual_reserve_escalation", reserve_escalation
        )
        object.__setattr__(
            self, "usage_since_event_at_lease_start", usage_since_event
        )


@dataclass(frozen=True)
class CaseInputs:
    """All assumptions required to run one aircraft lease case."""

    aircraft_type: str
    date_of_manufacture: date
    lessee: str
    lease_start_date: date
    analysis_date: date
    lease_expiry_date: date
    default_monthly_fh: Decimal | int | float | str
    default_monthly_fc: Decimal | int | float | str
    components: tuple[ComponentConfig, ...]
    utilization_overrides: tuple[UtilizationOverride, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.aircraft_type.strip():
            raise ValueError("aircraft_type must not be blank")
        if not self.lessee.strip():
            raise ValueError("lessee must not be blank")
        if not (
            self.date_of_manufacture
            <= self.lease_start_date
            <= self.analysis_date
            <= self.lease_expiry_date
        ):
            raise ValueError(
                "dates must satisfy manufacture <= lease start <= analysis <= lease expiry"
            )

        monthly_fh = to_decimal(self.default_monthly_fh, "default_monthly_fh")
        monthly_fc = to_decimal(self.default_monthly_fc, "default_monthly_fc")
        _require_nonnegative("default_monthly_fh", monthly_fh)
        _require_nonnegative("default_monthly_fc", monthly_fc)

        if not self.components:
            raise ValueError("at least one component is required")
        component_codes = [component.code for component in self.components]
        if len(component_codes) != len(set(component_codes)):
            raise ValueError("component codes must be unique")

        override_dates = [override.month_end for override in self.utilization_overrides]
        if len(override_dates) != len(set(override_dates)):
            raise ValueError("utilization override dates must be unique")
        for override in self.utilization_overrides:
            if not self.lease_start_date <= override.month_end <= self.lease_expiry_date:
                raise ValueError("utilization override must fall within the lease term")

        object.__setattr__(self, "default_monthly_fh", monthly_fh)
        object.__setattr__(self, "default_monthly_fc", monthly_fc)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the case."""

        return _serialize(asdict(self))

    def summary(self) -> dict[str, Any]:
        """Return a compact configuration summary for the Stage 0 CLI."""

        return {
            "aircraft_type": self.aircraft_type,
            "lessee": self.lessee,
            "date_of_manufacture": self.date_of_manufacture.isoformat(),
            "lease_start_date": self.lease_start_date.isoformat(),
            "analysis_date": self.analysis_date.isoformat(),
            "lease_expiry_date": self.lease_expiry_date.isoformat(),
            "default_monthly_fh": str(self.default_monthly_fh),
            "default_monthly_fc": str(self.default_monthly_fc),
            "component_codes": [component.code for component in self.components],
            "component_count": len(self.components),
            "utilization_override_count": len(self.utilization_overrides),
        }

