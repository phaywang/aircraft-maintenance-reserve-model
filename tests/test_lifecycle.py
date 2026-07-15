"""V2.0 lifecycle schema, chronology and V1 migration tests."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pandas as pd

from aircraft_cashflow.balances import build_full_reserve_balances
from aircraft_cashflow.config import build_default_case
from aircraft_cashflow.events import build_full_maintenance_calendar
from aircraft_cashflow.inflows import build_full_reserve_inflows
from aircraft_cashflow.lifecycle import (
    SCENARIO_SCHEMA_VERSION,
    CutoffPosition,
    KnownState,
    LeaseContract,
    ReserveAccountRule,
    Scenario,
    TransitionPeriod,
    UtilizationRegime,
    build_contract_periods,
    lifecycle_segments,
    migrate_v1_case,
    scenario_to_v1_case,
)
from aircraft_cashflow.utilization import build_full_utilization


class LifecycleMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = build_default_case()
        self.scenario = migrate_v1_case(self.case)

    def test_migrated_case_uses_versioned_single_lease_schema(self) -> None:
        self.assertEqual(self.scenario.schema_version, SCENARIO_SCHEMA_VERSION)
        self.assertEqual(len(self.scenario.leases), 1)
        self.assertEqual(len(self.scenario.transitions), 0)
        self.assertEqual(
            {rule.component_code for rule in self.scenario.leases[0].reserve_accounts},
            set(self.scenario.asset.component_codes),
        )
        self.assertTrue(
            all(
                rule.account_id.startswith("lease-1:")
                for rule in self.scenario.leases[0].reserve_accounts
            )
        )

    def test_v1_round_trip_preserves_inputs(self) -> None:
        self.assertEqual(scenario_to_v1_case(self.scenario).to_dict(), self.case.to_dict())

    def test_v1_round_trip_preserves_every_phase_one_calculation_row(self) -> None:
        round_trip = scenario_to_v1_case(self.scenario)
        builders = (
            build_full_utilization,
            build_full_maintenance_calendar,
            build_full_reserve_inflows,
            build_full_reserve_balances,
        )
        for builder in builders:
            with self.subTest(builder=builder.__name__):
                pd.testing.assert_frame_equal(
                    builder(round_trip),
                    builder(self.case),
                    check_exact=True,
                )

    def test_scenario_contract_is_json_serializable(self) -> None:
        payload = self.scenario.to_dict()
        encoded = json.dumps(payload)
        self.assertIn('"schema_version": "2.0"', encoded)
        self.assertFalse(any(isinstance(value, Decimal) for value in payload.values()))


class LifecycleChronologyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = migrate_v1_case(build_default_case())
        accounts = tuple(
            ReserveAccountRule(
                account_id=f"lease-2:{component.code}",
                component_code=component.code,
            )
            for component in self.base.asset.components
        )
        self.lease_1 = replace(
            self.base.leases[0],
            end_date=date(2026, 6, 30),
        )
        self.transition = TransitionPeriod(
            transition_id="transition-1",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
            description="Remarketing and delivery preparation",
        )
        self.lease_2 = LeaseContract(
            contract_id="lease-2",
            lessee="Follow-on Airline",
            start_date=date(2026, 8, 1),
            end_date=date(2029, 6, 30),
            reserve_accounts=accounts,
        )
        self.regime_1 = replace(
            self.base.utilization_regimes[0],
            end_date=self.lease_1.end_date,
        )
        self.regime_2 = UtilizationRegime(
            regime_id="lease-2-utilization",
            segment_id="lease-2",
            start_date=self.lease_2.start_date,
            end_date=self.lease_2.end_date,
            monthly_fh=Decimal("240"),
            monthly_fc=Decimal("90"),
        )

    def build_scenario(self, **changes: object) -> Scenario:
        values: dict[str, object] = {
            "scenario_id": "two-lease-demo",
            "name": "Two lease lifecycle",
            "asset": self.base.asset,
            "analysis_date": self.lease_1.end_date,
            "cutoff_position": CutoffPosition.AFTER_EXPIRY_SETTLEMENT,
            "valuation_date": self.lease_1.end_date,
            "comparison_horizon": self.lease_2.end_date,
            "leases": (self.lease_1, self.lease_2),
            "transitions": (self.transition,),
            "utilization_regimes": (self.regime_1, self.regime_2),
        }
        values.update(changes)
        return Scenario(**values)  # type: ignore[arg-type]

    def test_explicit_transition_closes_gap_between_leases(self) -> None:
        scenario = self.build_scenario()
        self.assertEqual(
            [segment.contract_id if isinstance(segment, LeaseContract) else segment.transition_id for segment in lifecycle_segments(scenario)],
            ["lease-1", "transition-1", "lease-2"],
        )

    def test_gap_without_transition_fails_clearly(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicit transition"):
            self.build_scenario(transitions=())

    def test_overlapping_segments_fail_clearly(self) -> None:
        overlapping = replace(self.lease_2, start_date=date(2026, 7, 31))
        with self.assertRaisesRegex(ValueError, "overlap"):
            self.build_scenario(leases=(self.lease_1, overlapping))

    def test_unknown_component_mapping_fails(self) -> None:
        bad_lease = replace(
            self.lease_2,
            reserve_accounts=(ReserveAccountRule("lease-2:BAD", "BAD"),),
        )
        with self.assertRaisesRegex(ValueError, "unknown component"):
            self.build_scenario(leases=(self.lease_1, bad_lease))

    def test_before_and_after_expiry_cutoffs_are_distinct(self) -> None:
        before = self.build_scenario(
            cutoff_position=CutoffPosition.BEFORE_EXPIRY_SETTLEMENT
        ).analysis_context()
        after = self.build_scenario(
            cutoff_position=CutoffPosition.AFTER_EXPIRY_SETTLEMENT
        ).analysis_context()
        self.assertTrue(before.expiry_settlement_pending)
        self.assertEqual(before.lease_id, "lease-1")
        self.assertFalse(after.expiry_settlement_pending)
        self.assertIsNone(after.lease_id)
        self.assertLess(before.settled_through, after.settled_through)

    def test_before_expiry_cutoff_is_rejected_on_non_expiry_date(self) -> None:
        with self.assertRaisesRegex(ValueError, "only on a lease expiry"):
            self.build_scenario(
                analysis_date=date(2026, 6, 29),
                valuation_date=date(2026, 6, 29),
                cutoff_position=CutoffPosition.BEFORE_EXPIRY_SETTLEMENT,
            )

    def test_known_state_cannot_reference_another_contract_account(self) -> None:
        state = KnownState(
            as_of_date=self.lease_1.end_date,
            ttsn="28000",
            tcsn="10500",
            reserve_account_balances={"unknown:6Y": "100"},
        )
        with self.assertRaisesRegex(ValueError, "unknown reserve accounts"):
            self.build_scenario(known_state=state)

    def test_actual_utilization_cannot_extend_past_analysis_date(self) -> None:
        future_actual = replace(
            self.regime_2,
            actual=True,
        )
        with self.assertRaisesRegex(ValueError, "actual utilization"):
            self.build_scenario(
                utilization_regimes=(self.regime_1, future_actual),
            )

    def test_overlapping_utilization_regimes_fail(self) -> None:
        second_regime = replace(
            self.regime_1,
            regime_id="lease-1-overlap",
            start_date=date(2026, 1, 1),
        )
        with self.assertRaisesRegex(ValueError, "utilization regimes overlap"):
            self.build_scenario(
                utilization_regimes=(self.regime_1, second_regime, self.regime_2),
            )


class ContractPeriodTests(unittest.TestCase):
    def test_arbitrary_dates_create_first_and_last_stub_periods(self) -> None:
        periods = build_contract_periods(
            date(2027, 1, 15), date(2027, 3, 10), due_day=31
        )
        self.assertEqual(len(periods), 3)
        self.assertEqual([period.day_count for period in periods], [17, 28, 10])
        self.assertEqual([period.is_stub for period in periods], [True, False, True])
        self.assertEqual(
            [period.due_date for period in periods],
            [date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31)],
        )

    def test_month_aligned_contract_has_no_stub_periods(self) -> None:
        periods = build_contract_periods(date(2027, 1, 1), date(2027, 2, 28))
        self.assertEqual([period.is_stub for period in periods], [False, False])


if __name__ == "__main__":
    unittest.main()
