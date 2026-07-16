"""V2 lifecycle schema and compatibility layer for the verified V1 engine."""

from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable

from .models import (
    CaseInputs,
    ComponentConfig,
    ReserveBasis,
    UtilizationOverride,
    to_decimal,
)


SCENARIO_SCHEMA_VERSION = "2.0"


class CutoffPosition(str, Enum):
    """Whether an expiry-date analysis occurs before or after close-out."""

    BEFORE_EXPIRY_SETTLEMENT = "before_expiry_settlement"
    AFTER_EXPIRY_SETTLEMENT = "after_expiry_settlement"


class ProrationConvention(str, Enum):
    """Contract convention for fixed cash flows in stub periods."""

    ACTUAL_DAYS = "actual_days"
    FULL_MONTH = "full_month"
    NONE = "none"


class UtilizationPattern(str, Enum):
    """How a dated utilization regime resolves monthly FH and FC."""

    FIXED_MONTHLY = "fixed_monthly"
    SEASONAL_PROFILE = "seasonal_profile"
    EXPLICIT_MONTHS = "explicit_months"


class TerminalValueBasis(str, Enum):
    """Source of the scenario terminal value."""

    SALE = "sale"
    APPRAISAL = "appraisal"
    CONTINUATION = "continuation"


class ReserveCloseoutRule(str, Enum):
    """Treatment of an unused reserve balance when a lease closes."""

    RETAIN_BY_LESSOR = "retain_by_lessor"
    REFUND_TO_LESSEE = "refund_to_lessee"
    OFFSET_REDELIVERY = "offset_redelivery"


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


def _require_nonnegative(name: str, value: Decimal) -> None:
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _require_identifier(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be blank")


@dataclass(frozen=True)
class AircraftAsset:
    """Physical aircraft and components, independent of any lease contract."""

    asset_id: str
    aircraft_type: str
    date_of_manufacture: date
    components: tuple[ComponentConfig, ...]

    def __post_init__(self) -> None:
        _require_identifier("asset_id", self.asset_id)
        _require_identifier("aircraft_type", self.aircraft_type)
        if not self.components:
            raise ValueError("aircraft asset must contain at least one component")
        codes = [component.code for component in self.components]
        if len(codes) != len(set(codes)):
            raise ValueError("aircraft component codes must be unique")

    @property
    def component_codes(self) -> tuple[str, ...]:
        return tuple(component.code for component in self.components)


@dataclass(frozen=True)
class ReserveAccountRule:
    """Lease-specific cash account mapped to one physical component."""

    account_id: str
    component_code: str
    reserve_basis: ReserveBasis | None = None
    base_rate: Decimal | int | float | str = Decimal("0")
    rate_base_date: date | None = None
    annual_escalation: Decimal | int | float | str = Decimal("0")
    closeout_rule: ReserveCloseoutRule = ReserveCloseoutRule.RETAIN_BY_LESSOR

    def __post_init__(self) -> None:
        _require_identifier("account_id", self.account_id)
        _require_identifier("component_code", self.component_code)
        if self.reserve_basis is not None and not isinstance(
            self.reserve_basis, ReserveBasis
        ):
            raise ValueError("reserve_basis must be a ReserveBasis")
        base_rate = to_decimal(self.base_rate, "reserve account base_rate")
        annual_escalation = to_decimal(
            self.annual_escalation, "reserve account annual_escalation"
        )
        _require_nonnegative("reserve account base_rate", base_rate)
        _require_nonnegative("reserve account annual_escalation", annual_escalation)
        if base_rate and self.reserve_basis is None:
            raise ValueError("a positive reserve rate requires a reserve_basis")
        if not isinstance(self.closeout_rule, ReserveCloseoutRule):
            raise ValueError("closeout_rule must be a ReserveCloseoutRule")
        object.__setattr__(self, "base_rate", base_rate)
        object.__setattr__(self, "annual_escalation", annual_escalation)


@dataclass(frozen=True)
class RedeliveryConditionRule:
    """Minimum remaining-life condition for one physical component."""

    component_code: str
    minimum_remaining_ratio: Decimal | int | float | str

    def __post_init__(self) -> None:
        _require_identifier("redelivery component_code", self.component_code)
        ratio = to_decimal(
            self.minimum_remaining_ratio, "minimum_remaining_ratio"
        )
        if ratio < 0 or ratio > 1:
            raise ValueError("minimum_remaining_ratio must be between zero and one")
        object.__setattr__(self, "minimum_remaining_ratio", ratio)


@dataclass(frozen=True)
class LeaseContract:
    """Dated lease and its contract-specific maintenance reserve accounts."""

    contract_id: str
    lessee: str
    start_date: date
    end_date: date
    reserve_accounts: tuple[ReserveAccountRule, ...]
    fixed_cash_proration: ProrationConvention = ProrationConvention.ACTUAL_DAYS
    due_day: int | None = None
    monthly_rent: Decimal | int | float | str = Decimal("0")
    rent_base_date: date | None = None
    annual_rent_escalation: Decimal | int | float | str = Decimal("0")
    redelivery_conditions: tuple[RedeliveryConditionRule, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        _require_identifier("contract_id", self.contract_id)
        _require_identifier("lessee", self.lessee)
        if self.start_date > self.end_date:
            raise ValueError("lease start_date must not be after end_date")
        if not isinstance(self.fixed_cash_proration, ProrationConvention):
            raise ValueError("fixed_cash_proration must be a ProrationConvention")
        if self.due_day is not None and not 1 <= self.due_day <= 31:
            raise ValueError("due_day must be between 1 and 31")
        monthly_rent = to_decimal(self.monthly_rent, "monthly_rent")
        annual_rent_escalation = to_decimal(
            self.annual_rent_escalation, "annual_rent_escalation"
        )
        _require_nonnegative("monthly_rent", monthly_rent)
        _require_nonnegative("annual_rent_escalation", annual_rent_escalation)
        rent_base_date = self.rent_base_date or self.start_date
        object.__setattr__(self, "monthly_rent", monthly_rent)
        object.__setattr__(self, "annual_rent_escalation", annual_rent_escalation)
        object.__setattr__(self, "rent_base_date", rent_base_date)
        account_ids = [rule.account_id for rule in self.reserve_accounts]
        component_codes = [rule.component_code for rule in self.reserve_accounts]
        if len(account_ids) != len(set(account_ids)):
            raise ValueError("reserve account identifiers must be unique within a lease")
        if len(component_codes) != len(set(component_codes)):
            raise ValueError("a physical component cannot map to multiple reserve accounts in one lease")
        condition_codes = [
            condition.component_code for condition in self.redelivery_conditions
        ]
        if len(condition_codes) != len(set(condition_codes)):
            raise ValueError("redelivery component conditions must be unique within a lease")


@dataclass(frozen=True)
class UtilizationRegime:
    """Dated utilization assumptions belonging to a lifecycle segment."""

    regime_id: str
    segment_id: str
    start_date: date
    end_date: date
    monthly_fh: Decimal | int | float | str
    monthly_fc: Decimal | int | float | str
    pattern: UtilizationPattern = UtilizationPattern.FIXED_MONTHLY
    actual: bool = False
    month_overrides: tuple[UtilizationOverride, ...] = field(default_factory=tuple)
    seasonal_fh_factors: tuple[Decimal | int | float | str, ...] = field(
        default_factory=tuple
    )
    seasonal_fc_factors: tuple[Decimal | int | float | str, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        _require_identifier("regime_id", self.regime_id)
        _require_identifier("segment_id", self.segment_id)
        if self.start_date > self.end_date:
            raise ValueError("utilization regime start_date must not be after end_date")
        if not isinstance(self.pattern, UtilizationPattern):
            raise ValueError("pattern must be a UtilizationPattern")
        monthly_fh = to_decimal(self.monthly_fh, "monthly_fh")
        monthly_fc = to_decimal(self.monthly_fc, "monthly_fc")
        _require_nonnegative("monthly_fh", monthly_fh)
        _require_nonnegative("monthly_fc", monthly_fc)
        fh_factors = tuple(
            to_decimal(value, "seasonal_fh_factors")
            for value in self.seasonal_fh_factors
        )
        fc_factors = tuple(
            to_decimal(value, "seasonal_fc_factors")
            for value in self.seasonal_fc_factors
        )
        for factor in (*fh_factors, *fc_factors):
            _require_nonnegative("seasonal utilization factor", factor)
        if self.pattern is UtilizationPattern.SEASONAL_PROFILE:
            if len(fh_factors) != 12 or len(fc_factors) != 12:
                raise ValueError(
                    "seasonal utilization requires 12 FH factors and 12 FC factors"
                )
        elif fh_factors or fc_factors:
            raise ValueError("seasonal factors are valid only for a seasonal profile")

        override_dates = [override.month_end for override in self.month_overrides]
        if len(override_dates) != len(set(override_dates)):
            raise ValueError("utilization regime override dates must be unique")
        for override in self.month_overrides:
            override_month = (override.month_end.year, override.month_end.month)
            start_month = (self.start_date.year, self.start_date.month)
            end_month = (self.end_date.year, self.end_date.month)
            if not start_month <= override_month <= end_month:
                raise ValueError("utilization regime override month must overlap its regime")
        object.__setattr__(self, "monthly_fh", monthly_fh)
        object.__setattr__(self, "monthly_fc", monthly_fc)
        object.__setattr__(self, "seasonal_fh_factors", fh_factors)
        object.__setattr__(self, "seasonal_fc_factors", fc_factors)


@dataclass(frozen=True)
class TransitionPeriod:
    """Explicit non-lease lifecycle segment such as storage or preparation."""

    transition_id: str
    start_date: date
    end_date: date
    description: str = "Transition"

    def __post_init__(self) -> None:
        _require_identifier("transition_id", self.transition_id)
        _require_identifier("description", self.description)
        if self.start_date > self.end_date:
            raise ValueError("transition start_date must not be after end_date")


@dataclass(frozen=True)
class TerminalValue:
    """Value applied at the common comparison horizon."""

    as_of_date: date
    amount: Decimal | int | float | str
    basis: TerminalValueBasis
    selling_cost: Decimal | int | float | str = Decimal("0")

    def __post_init__(self) -> None:
        amount = to_decimal(self.amount, "terminal value amount")
        selling_cost = to_decimal(self.selling_cost, "terminal selling_cost")
        _require_nonnegative("terminal value amount", amount)
        _require_nonnegative("terminal selling_cost", selling_cost)
        if not isinstance(self.basis, TerminalValueBasis):
            raise ValueError("terminal value basis must be a TerminalValueBasis")
        object.__setattr__(self, "amount", amount)
        object.__setattr__(self, "selling_cost", selling_cost)


@dataclass(frozen=True)
class KnownState:
    """Actual technical and cash state loaded at an analysis cut-off."""

    as_of_date: date
    ttsn: Decimal | int | float | str
    tcsn: Decimal | int | float | str
    component_usage_since_event: dict[str, Decimal | int | float | str] = field(
        default_factory=dict
    )
    reserve_account_balances: dict[str, Decimal | int | float | str] = field(
        default_factory=dict
    )
    component_last_event_dates: dict[str, date] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ttsn = to_decimal(self.ttsn, "known state ttsn")
        tcsn = to_decimal(self.tcsn, "known state tcsn")
        _require_nonnegative("known state ttsn", ttsn)
        _require_nonnegative("known state tcsn", tcsn)
        component_usage = {
            code: to_decimal(value, f"component usage {code}")
            for code, value in self.component_usage_since_event.items()
        }
        balances = {
            account_id: to_decimal(value, f"reserve balance {account_id}")
            for account_id, value in self.reserve_account_balances.items()
        }
        for code, value in component_usage.items():
            _require_nonnegative(f"component usage {code}", value)
        for account_id, value in balances.items():
            _require_nonnegative(f"reserve balance {account_id}", value)
        for code, event_date in self.component_last_event_dates.items():
            if event_date > self.as_of_date:
                raise ValueError(
                    f"last event date for {code} cannot be after known-state date"
                )
        object.__setattr__(self, "ttsn", ttsn)
        object.__setattr__(self, "tcsn", tcsn)
        object.__setattr__(self, "component_usage_since_event", component_usage)
        object.__setattr__(self, "reserve_account_balances", balances)


@dataclass(frozen=True)
class AnalysisContext:
    """Resolved lifecycle position at the selected analysis cut-off."""

    segment_id: str | None
    lease_id: str | None
    expiry_settlement_pending: bool
    settled_through: date


@dataclass(frozen=True)
class Scenario:
    """Versioned V2 aircraft lifecycle scenario."""

    scenario_id: str
    name: str
    asset: AircraftAsset
    analysis_date: date
    cutoff_position: CutoffPosition
    valuation_date: date
    comparison_horizon: date
    leases: tuple[LeaseContract, ...]
    utilization_regimes: tuple[UtilizationRegime, ...]
    transitions: tuple[TransitionPeriod, ...] = field(default_factory=tuple)
    terminal_value: TerminalValue | None = None
    known_state: KnownState | None = None
    currency: str = "USD"
    schema_version: str = SCENARIO_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_identifier("scenario_id", self.scenario_id)
        _require_identifier("scenario name", self.name)
        _require_identifier("currency", self.currency)
        if self.schema_version != SCENARIO_SCHEMA_VERSION:
            raise ValueError(f"unsupported scenario schema_version {self.schema_version!r}")
        if not isinstance(self.cutoff_position, CutoffPosition):
            raise ValueError("cutoff_position must be a CutoffPosition")
        if not self.leases:
            raise ValueError("scenario must contain at least one lease")
        if self.valuation_date > self.analysis_date:
            raise ValueError("valuation_date must not be after analysis_date")
        if self.analysis_date > self.comparison_horizon:
            raise ValueError("analysis_date must not be after comparison_horizon")
        if self.asset.date_of_manufacture > min(lease.start_date for lease in self.leases):
            raise ValueError("aircraft manufacture date must not be after its first lease")

        lease_ids = [lease.contract_id for lease in self.leases]
        transition_ids = [transition.transition_id for transition in self.transitions]
        regime_ids = [regime.regime_id for regime in self.utilization_regimes]
        segment_ids = lease_ids + transition_ids
        if len(lease_ids) != len(set(lease_ids)):
            raise ValueError("lease contract identifiers must be unique")
        if len(transition_ids) != len(set(transition_ids)):
            raise ValueError("transition identifiers must be unique")
        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError("lease and transition identifiers must be globally unique")
        if len(regime_ids) != len(set(regime_ids)):
            raise ValueError("utilization regime identifiers must be unique")

        component_codes = set(self.asset.component_codes)
        valid_account_ids: set[str] = set()
        for lease in self.leases:
            for rule in lease.reserve_accounts:
                if rule.component_code not in component_codes:
                    raise ValueError(
                        f"reserve account {rule.account_id!r} references unknown component "
                        f"{rule.component_code!r}"
                    )
                if rule.account_id in valid_account_ids:
                    raise ValueError("reserve account identifiers must be unique across leases")
                valid_account_ids.add(rule.account_id)
            unknown_conditions = {
                condition.component_code
                for condition in lease.redelivery_conditions
            } - component_codes
            if unknown_conditions:
                raise ValueError(
                    f"redelivery conditions reference unknown components: "
                    f"{sorted(unknown_conditions)}"
                )

        segments = sorted(
            [
                (lease.start_date, lease.end_date, lease.contract_id)
                for lease in self.leases
            ]
            + [
                (transition.start_date, transition.end_date, transition.transition_id)
                for transition in self.transitions
            ],
            key=lambda segment: (segment[0], segment[1], segment[2]),
        )
        for previous, current in zip(segments, segments[1:]):
            if current[0] <= previous[1]:
                raise ValueError(
                    f"lifecycle segments {previous[2]!r} and {current[2]!r} overlap"
                )
            if current[0] != previous[1] + timedelta(days=1):
                raise ValueError(
                    f"gap between lifecycle segments {previous[2]!r} and {current[2]!r}; "
                    "add an explicit transition period"
                )
        if self.comparison_horizon > segments[-1][1]:
            raise ValueError("comparison_horizon extends beyond the final lifecycle segment")
        if self.analysis_date < segments[0][0] or self.analysis_date > segments[-1][1]:
            raise ValueError("analysis_date must fall within the modeled lifecycle")

        if self.cutoff_position is CutoffPosition.BEFORE_EXPIRY_SETTLEMENT and not any(
            self.analysis_date == lease.end_date for lease in self.leases
        ):
            raise ValueError(
                "before-expiry-settlement cutoff is valid only on a lease expiry date"
            )

        regimes_by_segment: dict[str, list[UtilizationRegime]] = {}
        for regime in self.utilization_regimes:
            if regime.segment_id not in segment_ids:
                raise ValueError(
                    f"utilization regime {regime.regime_id!r} references unknown segment "
                    f"{regime.segment_id!r}"
                )
            segment = next(item for item in segments if item[2] == regime.segment_id)
            if regime.start_date < segment[0] or regime.end_date > segment[1]:
                raise ValueError("utilization regime must fall within its lifecycle segment")
            if regime.actual and regime.end_date > self.analysis_date:
                raise ValueError("actual utilization cannot extend beyond the analysis date")
            regimes_by_segment.setdefault(regime.segment_id, []).append(regime)
        for segment_id, regimes in regimes_by_segment.items():
            ordered_regimes = sorted(
                regimes, key=lambda regime: (regime.start_date, regime.end_date)
            )
            for previous, current in zip(ordered_regimes, ordered_regimes[1:]):
                if current.start_date <= previous.end_date:
                    raise ValueError(
                        f"utilization regimes overlap within segment {segment_id!r}"
                    )

        if self.known_state is not None:
            if self.known_state.as_of_date > self.analysis_date:
                raise ValueError("known state cannot be dated after the analysis date")
            if (
                self.cutoff_position is CutoffPosition.BEFORE_EXPIRY_SETTLEMENT
                and self.known_state.as_of_date >= self.analysis_date
            ):
                raise ValueError(
                    "before-expiry-settlement known state must be settled through "
                    "the day before expiry"
                )
            unknown_components = set(self.known_state.component_usage_since_event) - component_codes
            if unknown_components:
                raise ValueError(
                    f"known state references unknown components: {sorted(unknown_components)}"
                )
            unknown_accounts = set(self.known_state.reserve_account_balances) - valid_account_ids
            if unknown_accounts:
                raise ValueError(
                    f"known state references unknown reserve accounts: {sorted(unknown_accounts)}"
                )
            unknown_event_dates = (
                set(self.known_state.component_last_event_dates) - component_codes
            )
            if unknown_event_dates:
                raise ValueError(
                    f"known state references unknown component event dates: "
                    f"{sorted(unknown_event_dates)}"
                )

        if self.terminal_value is not None:
            if self.terminal_value.as_of_date != self.comparison_horizon:
                raise ValueError("terminal value date must equal comparison_horizon")

    def analysis_context(self) -> AnalysisContext:
        """Resolve whether expiry settlement is pending at the cut-off."""

        expiry_lease = next(
            (lease for lease in self.leases if lease.end_date == self.analysis_date), None
        )
        if (
            expiry_lease is not None
            and self.cutoff_position is CutoffPosition.BEFORE_EXPIRY_SETTLEMENT
        ):
            return AnalysisContext(
                segment_id=expiry_lease.contract_id,
                lease_id=expiry_lease.contract_id,
                expiry_settlement_pending=True,
                settled_through=self.analysis_date - timedelta(days=1),
            )
        if expiry_lease is not None:
            return AnalysisContext(
                segment_id=None,
                lease_id=None,
                expiry_settlement_pending=False,
                settled_through=self.analysis_date,
            )

        active_lease = next(
            (
                lease
                for lease in self.leases
                if lease.start_date <= self.analysis_date <= lease.end_date
            ),
            None,
        )
        active_transition = next(
            (
                transition
                for transition in self.transitions
                if transition.start_date <= self.analysis_date <= transition.end_date
            ),
            None,
        )
        return AnalysisContext(
            segment_id=(active_lease.contract_id if active_lease else active_transition.transition_id if active_transition else None),
            lease_id=active_lease.contract_id if active_lease else None,
            expiry_settlement_pending=False,
            settled_through=self.analysis_date,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the versioned scenario contract as JSON-serializable data."""

        return _serialize(asdict(self))


@dataclass(frozen=True)
class ContractPeriod:
    """Explicit calendar period, including partial first and last months."""

    period_number: int
    start_date: date
    end_date: date
    due_date: date
    is_stub: bool
    day_count: int
    days_in_month: int


def build_contract_periods(
    start_date: date, end_date: date, due_day: int | None = None
) -> tuple[ContractPeriod, ...]:
    """Build inclusive calendar periods without assuming month-end contract dates."""

    if start_date > end_date:
        raise ValueError("period start_date must not be after end_date")
    if due_day is not None and not 1 <= due_day <= 31:
        raise ValueError("due_day must be between 1 and 31")

    periods: list[ContractPeriod] = []
    current = start_date
    while current <= end_date:
        last_day = calendar.monthrange(current.year, current.month)[1]
        calendar_end = date(current.year, current.month, last_day)
        period_end = min(calendar_end, end_date)
        if due_day is None:
            due_date = period_end
        else:
            due_date = date(
                period_end.year,
                period_end.month,
                min(due_day, calendar.monthrange(period_end.year, period_end.month)[1]),
            )
        day_count = (period_end - current).days + 1
        periods.append(
            ContractPeriod(
                period_number=len(periods) + 1,
                start_date=current,
                end_date=period_end,
                due_date=due_date,
                is_stub=current.day != 1 or period_end.day != last_day,
                day_count=day_count,
                days_in_month=last_day,
            )
        )
        current = period_end + timedelta(days=1)
    return tuple(periods)


def migrate_v1_case(case: CaseInputs, scenario_id: str = "v1-migrated") -> Scenario:
    """Wrap one verified V1 lease in the V2 lifecycle schema without recalculation."""

    contract_id = "lease-1"
    asset = AircraftAsset(
        asset_id="aircraft-1",
        aircraft_type=case.aircraft_type,
        date_of_manufacture=case.date_of_manufacture,
        components=case.components,
    )
    lease = LeaseContract(
        contract_id=contract_id,
        lessee=case.lessee,
        start_date=case.lease_start_date,
        end_date=case.lease_expiry_date,
        reserve_accounts=tuple(
            ReserveAccountRule(
                account_id=f"{contract_id}:{component.code}",
                component_code=component.code,
                reserve_basis=component.reserve_basis,
                base_rate=component.base_reserve_rate,
                rate_base_date=component.reserve_rate_base_date,
                annual_escalation=component.annual_reserve_escalation,
            )
            for component in case.components
        ),
        fixed_cash_proration=ProrationConvention.FULL_MONTH,
    )
    regime = UtilizationRegime(
        regime_id="lease-1-utilization",
        segment_id=contract_id,
        start_date=case.lease_start_date,
        end_date=case.lease_expiry_date,
        monthly_fh=case.default_monthly_fh,
        monthly_fc=case.default_monthly_fc,
        pattern=UtilizationPattern.FIXED_MONTHLY,
        actual=False,
        month_overrides=case.utilization_overrides,
    )
    return Scenario(
        scenario_id=scenario_id,
        name=f"{case.aircraft_type} single-lease migration",
        asset=asset,
        analysis_date=case.analysis_date,
        cutoff_position=CutoffPosition.AFTER_EXPIRY_SETTLEMENT,
        valuation_date=case.analysis_date,
        comparison_horizon=case.lease_expiry_date,
        leases=(lease,),
        utilization_regimes=(regime,),
    )


def scenario_to_v1_case(scenario: Scenario) -> CaseInputs:
    """Return a V1-compatible case when a scenario is exactly one supported lease."""

    if len(scenario.leases) != 1 or scenario.transitions:
        raise ValueError("V1 compatibility requires exactly one lease and no transitions")
    lease = scenario.leases[0]
    regimes = [
        regime
        for regime in scenario.utilization_regimes
        if regime.segment_id == lease.contract_id
    ]
    if len(regimes) != 1:
        raise ValueError("V1 compatibility requires one utilization regime for the lease")
    regime = regimes[0]
    if regime.pattern is not UtilizationPattern.FIXED_MONTHLY:
        raise ValueError("V1 compatibility supports fixed monthly utilization only")
    if regime.start_date != lease.start_date or regime.end_date != lease.end_date:
        raise ValueError("V1-compatible utilization must cover the complete lease")
    if scenario.known_state is not None:
        raise ValueError("V1 compatibility does not accept an externally loaded known state")

    mapped_components = {rule.component_code for rule in lease.reserve_accounts}
    if mapped_components != set(scenario.asset.component_codes):
        raise ValueError("V1 compatibility requires one reserve account per component")

    return CaseInputs(
        aircraft_type=scenario.asset.aircraft_type,
        date_of_manufacture=scenario.asset.date_of_manufacture,
        lessee=lease.lessee,
        lease_start_date=lease.start_date,
        analysis_date=scenario.analysis_date,
        lease_expiry_date=lease.end_date,
        default_monthly_fh=regime.monthly_fh,
        default_monthly_fc=regime.monthly_fc,
        components=scenario.asset.components,
        utilization_overrides=regime.month_overrides,
    )


def lifecycle_segments(
    scenario: Scenario,
) -> Iterable[LeaseContract | TransitionPeriod]:
    """Yield all lifecycle segments in chronological order."""

    return iter(
        sorted(
            (*scenario.leases, *scenario.transitions),
            key=lambda segment: (segment.start_date, segment.end_date),
        )
    )
