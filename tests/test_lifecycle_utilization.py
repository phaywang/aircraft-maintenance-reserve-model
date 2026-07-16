"""V2.1 dated and variable utilization timeline tests."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from aircraft_cashflow.config import build_default_case
from aircraft_cashflow.lifecycle import (
    CutoffPosition,
    KnownState,
    LeaseContract,
    ReserveAccountRule,
    Scenario,
    TransitionPeriod,
    UtilizationPattern,
    UtilizationRegime,
    migrate_v1_case,
)
from aircraft_cashflow.lifecycle_utilization import (
    LIFECYCLE_UTILIZATION_COLUMNS,
    build_forecast_lifecycle_utilization,
    build_lifecycle_utilization,
)
from aircraft_cashflow.models import UtilizationOverride


class LifecycleUtilizationTests(unittest.TestCase):
    def setUp(self) -> None:
        base = migrate_v1_case(build_default_case())
        self.asset = base.asset
        self.accounts_1 = tuple(
            ReserveAccountRule(f"lease-1:{code}", code)
            for code in self.asset.component_codes
        )
        self.accounts_2 = tuple(
            ReserveAccountRule(f"lease-2:{code}", code)
            for code in self.asset.component_codes
        )

    def scenario(
        self,
        *,
        leases: tuple[LeaseContract, ...],
        regimes: tuple[UtilizationRegime, ...],
        analysis_date: date,
        comparison_horizon: date,
        transitions: tuple[TransitionPeriod, ...] = (),
        known_state: KnownState | None = None,
    ) -> Scenario:
        return Scenario(
            scenario_id="variable-utilization-test",
            name="Variable utilization test",
            asset=self.asset,
            analysis_date=analysis_date,
            cutoff_position=CutoffPosition.AFTER_EXPIRY_SETTLEMENT,
            valuation_date=analysis_date,
            comparison_horizon=comparison_horizon,
            leases=leases,
            transitions=transitions,
            utilization_regimes=regimes,
            known_state=known_state,
        )

    def test_fixed_seasonal_and_explicit_months_are_prorated(self) -> None:
        lease = LeaseContract(
            "lease-1", "Airline", date(2027, 1, 15), date(2027, 3, 10), self.accounts_1
        )
        january = UtilizationRegime(
            "jan", "lease-1", date(2027, 1, 15), date(2027, 1, 31), 310, 155
        )
        factors = (1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1)
        february = UtilizationRegime(
            "feb",
            "lease-1",
            date(2027, 2, 1),
            date(2027, 2, 28),
            280,
            140,
            pattern=UtilizationPattern.SEASONAL_PROFILE,
            seasonal_fh_factors=factors,
            seasonal_fc_factors=factors,
        )
        march = UtilizationRegime(
            "mar",
            "lease-1",
            date(2027, 3, 1),
            date(2027, 3, 10),
            0,
            0,
            pattern=UtilizationPattern.EXPLICIT_MONTHS,
            month_overrides=(UtilizationOverride(date(2027, 3, 31), 310, 155),),
        )
        timeline = build_lifecycle_utilization(
            self.scenario(
                leases=(lease,),
                regimes=(january, february, march),
                analysis_date=date(2027, 2, 28),
                comparison_horizon=lease.end_date,
            )
        )
        self.assertEqual(list(timeline["input_source"]), ["fixed_monthly", "seasonal_profile", "override"])
        self.assertEqual(list(timeline["flight_hours"]), [Decimal("170"), Decimal("560"), Decimal("100")])
        self.assertEqual(list(timeline["flight_cycles"]), [Decimal("85"), Decimal("280"), Decimal("50")])
        self.assertEqual(timeline.iloc[-1]["ttsn"], Decimal("830"))
        self.assertEqual(timeline.iloc[-1]["tcsn"], Decimal("415"))

    def test_regime_change_inside_one_month_creates_auditable_slices(self) -> None:
        lease = LeaseContract(
            "lease-1", "Airline", date(2027, 1, 1), date(2027, 1, 31), self.accounts_1
        )
        regimes = (
            UtilizationRegime("low", "lease-1", date(2027, 1, 1), date(2027, 1, 15), 310, 155),
            UtilizationRegime("high", "lease-1", date(2027, 1, 16), date(2027, 1, 31), 620, 310),
        )
        timeline = build_lifecycle_utilization(
            self.scenario(
                leases=(lease,), regimes=regimes, analysis_date=lease.end_date, comparison_horizon=lease.end_date
            )
        )
        self.assertEqual(list(timeline["regime_id"]), ["low", "high"])
        self.assertEqual(list(timeline["day_count"]), [15, 16])
        self.assertEqual(timeline.iloc[-1]["ttsn"], Decimal("470"))

    def test_zero_flight_transition_preserves_cumulative_usage(self) -> None:
        lease_1 = LeaseContract(
            "lease-1", "Airline A", date(2027, 1, 1), date(2027, 1, 31), self.accounts_1
        )
        transition = TransitionPeriod(
            "transition-1", date(2027, 2, 1), date(2027, 2, 28), "Storage"
        )
        lease_2 = LeaseContract(
            "lease-2", "Airline B", date(2027, 3, 1), date(2027, 3, 31), self.accounts_2
        )
        regimes = (
            UtilizationRegime("lease-1-use", "lease-1", lease_1.start_date, lease_1.end_date, 310, 155),
            UtilizationRegime("storage", "transition-1", transition.start_date, transition.end_date, 0, 0),
            UtilizationRegime("lease-2-use", "lease-2", lease_2.start_date, lease_2.end_date, 620, 310),
        )
        timeline = build_lifecycle_utilization(
            self.scenario(
                leases=(lease_1, lease_2),
                transitions=(transition,),
                regimes=regimes,
                analysis_date=lease_1.end_date,
                comparison_horizon=lease_2.end_date,
            )
        )
        storage = timeline.loc[timeline["segment_type"] == "transition"].iloc[0]
        self.assertEqual(storage["flight_hours"], Decimal("0"))
        self.assertEqual(storage["ttsn"], Decimal("310"))
        self.assertEqual(timeline.iloc[-1]["ttsn"], Decimal("930"))

    def test_missing_transition_regime_fails_instead_of_assuming_zero(self) -> None:
        lease_1 = LeaseContract(
            "lease-1", "Airline A", date(2027, 1, 1), date(2027, 1, 31), self.accounts_1
        )
        transition = TransitionPeriod(
            "transition-1", date(2027, 2, 1), date(2027, 2, 28), "Storage"
        )
        lease_2 = LeaseContract(
            "lease-2", "Airline B", date(2027, 3, 1), date(2027, 3, 31), self.accounts_2
        )
        regimes = (
            UtilizationRegime("lease-1-use", "lease-1", lease_1.start_date, lease_1.end_date, 310, 155),
            UtilizationRegime("lease-2-use", "lease-2", lease_2.start_date, lease_2.end_date, 620, 310),
        )
        scenario = self.scenario(
            leases=(lease_1, lease_2), transitions=(transition,), regimes=regimes,
            analysis_date=lease_1.end_date, comparison_horizon=lease_2.end_date,
        )
        with self.assertRaisesRegex(ValueError, "explicit zero-flight regime"):
            build_lifecycle_utilization(scenario)

    def test_known_state_is_authoritative_opening_anchor(self) -> None:
        lease = LeaseContract(
            "lease-1", "Airline", date(2027, 1, 1), date(2027, 3, 31), self.accounts_1
        )
        regime = UtilizationRegime(
            "use", "lease-1", lease.start_date, lease.end_date, 310, 155
        )
        state = KnownState(date(2027, 2, 15), 10000, 5000)
        timeline = build_lifecycle_utilization(
            self.scenario(
                leases=(lease,), regimes=(regime,), analysis_date=state.as_of_date,
                comparison_horizon=lease.end_date, known_state=state,
            )
        )
        self.assertEqual(timeline.iloc[0]["input_source"], "known_state")
        self.assertEqual(timeline.iloc[0]["ttsn"], Decimal("10000"))
        february_stub = Decimal("310") * Decimal("13") / Decimal("28")
        self.assertEqual(timeline.iloc[1]["flight_hours"], february_stub)
        self.assertEqual(
            timeline.iloc[-1]["ttsn"], Decimal("10000") + february_stub + Decimal("310")
        )

    def test_analysis_date_is_an_explicit_timeline_boundary(self) -> None:
        lease = LeaseContract(
            "lease-1", "Airline", date(2027, 1, 1), date(2027, 1, 31), self.accounts_1
        )
        regime = UtilizationRegime(
            "use", "lease-1", lease.start_date, lease.end_date, 310, 155
        )
        scenario = self.scenario(
            leases=(lease,), regimes=(regime,), analysis_date=date(2027, 1, 15),
            comparison_horizon=lease.end_date,
        )
        timeline = build_lifecycle_utilization(scenario)
        forecast = build_forecast_lifecycle_utilization(scenario)
        self.assertEqual(list(timeline["day_count"]), [15, 16])
        self.assertEqual(forecast.iloc[0]["date"], date(2027, 1, 15))
        self.assertEqual(forecast.iloc[-1]["ttsn"], Decimal("310"))

    def test_explicit_month_pattern_rejects_missing_month(self) -> None:
        lease = LeaseContract(
            "lease-1", "Airline", date(2027, 1, 1), date(2027, 1, 31), self.accounts_1
        )
        regime = UtilizationRegime(
            "explicit", "lease-1", lease.start_date, lease.end_date, 0, 0,
            pattern=UtilizationPattern.EXPLICIT_MONTHS,
        )
        scenario = self.scenario(
            leases=(lease,), regimes=(regime,), analysis_date=lease.end_date,
            comparison_horizon=lease.end_date,
        )
        with self.assertRaisesRegex(ValueError, "requires an explicit override"):
            build_lifecycle_utilization(scenario)

    def test_seasonal_profile_requires_twelve_factors(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires 12 FH factors"):
            UtilizationRegime(
                "seasonal", "lease-1", date(2027, 1, 1), date(2027, 1, 31), 100, 50,
                pattern=UtilizationPattern.SEASONAL_PROFILE,
                seasonal_fh_factors=(1,), seasonal_fc_factors=(1,),
            )

    def test_output_contract_has_stable_column_order(self) -> None:
        lease = LeaseContract(
            "lease-1", "Airline", date(2027, 1, 1), date(2027, 1, 31), self.accounts_1
        )
        regime = UtilizationRegime(
            "use", "lease-1", lease.start_date, lease.end_date, 310, 155
        )
        timeline = build_lifecycle_utilization(
            self.scenario(
                leases=(lease,), regimes=(regime,), analysis_date=lease.end_date,
                comparison_horizon=lease.end_date,
            )
        )
        self.assertEqual(tuple(timeline.columns), LIFECYCLE_UTILIZATION_COLUMNS)


if __name__ == "__main__":
    unittest.main()
