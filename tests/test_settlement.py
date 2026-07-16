"""V2.3 maintenance settlement and redelivery close-out tests."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from aircraft_cashflow.lifecycle import (
    AircraftAsset, CutoffPosition, KnownState, LeaseContract,
    RedeliveryConditionRule, ReserveAccountRule, ReserveCloseoutRule,
    Scenario, TransitionPeriod, UtilizationRegime,
)
from aircraft_cashflow.models import ComponentConfig, EventDriver, ReserveBasis
from aircraft_cashflow.settlement import build_lifecycle_settlement


class SettlementTests(unittest.TestCase):
    def usage_component(self, interval: int = 100) -> ComponentConfig:
        return ComponentConfig(
            "E1", "Engine", EventDriver.FLIGHT_HOURS, interval, 1000,
            date(2027, 1, 1), 0, ReserveBasis.PER_FLIGHT_HOUR, 0,
            date(2027, 1, 1), 0, usage_since_event_at_lease_start=0,
        )

    def account(
        self, rate: int, closeout: ReserveCloseoutRule = ReserveCloseoutRule.RETAIN_BY_LESSOR
    ) -> ReserveAccountRule:
        return ReserveAccountRule(
            "lease-1:E1", "E1", ReserveBasis.PER_FLIGHT_HOUR, rate,
            date(2027, 1, 1), 0, closeout,
        )

    def scenario(
        self, component: ComponentConfig, lease: LeaseContract,
        regimes: tuple[UtilizationRegime, ...], *,
        analysis_date: date | None = None,
        cutoff: CutoffPosition = CutoffPosition.AFTER_EXPIRY_SETTLEMENT,
        transitions: tuple[TransitionPeriod, ...] = (),
        known_state: KnownState | None = None,
    ) -> Scenario:
        return Scenario(
            "settlement-test", "Settlement test",
            AircraftAsset("asset", "Test Aircraft", date(2027, 1, 1), (component,)),
            analysis_date or lease.end_date, cutoff, analysis_date or lease.end_date,
            transitions[-1].end_date if transitions else lease.end_date,
            (lease,), regimes, transitions, known_state=known_state,
        )

    def test_expiry_period_inflow_precedes_event_reimbursement(self) -> None:
        component = self.usage_component(100)
        lease = LeaseContract(
            "lease-1", "Airline", date(2027, 1, 1), date(2027, 1, 31),
            (self.account(6),),
        )
        regime = UtilizationRegime(
            "use", "lease-1", lease.start_date, lease.end_date, 100, 50
        )
        result = build_lifecycle_settlement(
            self.scenario(component, lease, (regime,))
        )
        event = result.events.iloc[0]
        ledger = result.reserve_ledger.iloc[0]
        self.assertEqual(event["date"], lease.end_date)
        self.assertEqual(event["available_reserve"], Decimal("600"))
        self.assertEqual(event["reserve_reimbursement"], Decimal("600"))
        self.assertEqual(event["unfunded_amount"], Decimal("400"))
        self.assertEqual(ledger["reserve_inflow"], Decimal("600"))
        self.assertTrue(ledger["account_closed"])

    def test_redelivery_shortfall_can_be_offset_by_unused_reserve(self) -> None:
        component = self.usage_component(100)
        lease = LeaseContract(
            "lease-1", "Airline", date(2027, 1, 1), date(2027, 1, 31),
            (self.account(1, ReserveCloseoutRule.OFFSET_REDELIVERY),),
            redelivery_conditions=(RedeliveryConditionRule("E1", "0.50"),),
        )
        regime = UtilizationRegime(
            "use", "lease-1", lease.start_date, lease.end_date, 60, 30
        )
        result = build_lifecycle_settlement(
            self.scenario(component, lease, (regime,))
        )
        redelivery = result.redelivery.iloc[0]
        ledger = result.reserve_ledger.iloc[0]
        self.assertEqual(redelivery["actual_remaining_ratio"], Decimal("0.4"))
        self.assertEqual(redelivery["gross_compensation"], Decimal("100.00"))
        self.assertEqual(redelivery["reserve_offset"], Decimal("60"))
        self.assertEqual(redelivery["net_cash_compensation"], Decimal("40.00"))
        self.assertEqual(ledger["closing_balance"], Decimal("0"))

    def test_refund_and_retention_closeout_rules_are_distinct(self) -> None:
        component = self.usage_component(100)
        for rule, refund, retained in (
            (ReserveCloseoutRule.REFUND_TO_LESSEE, Decimal("20"), Decimal("0")),
            (ReserveCloseoutRule.RETAIN_BY_LESSOR, Decimal("0"), Decimal("20")),
        ):
            with self.subTest(rule=rule):
                lease = LeaseContract(
                    "lease-1", "Airline", date(2027, 1, 1), date(2027, 1, 31),
                    (self.account(1, rule),),
                )
                regime = UtilizationRegime(
                    "use", "lease-1", lease.start_date, lease.end_date, 20, 10
                )
                ledger = build_lifecycle_settlement(
                    self.scenario(component, lease, (regime,))
                ).reserve_ledger.iloc[0]
                self.assertEqual(ledger["refund_to_lessee"], refund)
                self.assertEqual(ledger["retained_by_lessor"], retained)

    def test_transition_event_has_no_lease_account_and_is_unfunded(self) -> None:
        component = self.usage_component(100)
        lease = LeaseContract(
            "lease-1", "Airline", date(2027, 1, 1), date(2027, 1, 31),
            (self.account(1),),
        )
        transition = TransitionPeriod(
            "transition", date(2027, 2, 1), date(2027, 2, 28), "Ferry"
        )
        regimes = (
            UtilizationRegime("lease-use", "lease-1", lease.start_date, lease.end_date, 50, 25),
            UtilizationRegime("ferry-use", "transition", transition.start_date, transition.end_date, 50, 25),
        )
        result = build_lifecycle_settlement(
            self.scenario(component, lease, regimes, transitions=(transition,))
        )
        event = result.events.iloc[0]
        self.assertEqual(event["segment_type"], "transition")
        self.assertIsNone(event["account_id"])
        self.assertEqual(event["unfunded_amount"], Decimal("1000"))

    def test_calendar_event_on_expiry_resets_redelivery_state(self) -> None:
        component = ComponentConfig(
            "6Y", "Calendar check", EventDriver.CALENDAR_MONTHS, 1, 1000,
            date(2027, 1, 31), 0, ReserveBasis.PER_MONTH, 0,
            date(2027, 1, 31), 0, last_event_date=date(2027, 1, 31),
        )
        account = ReserveAccountRule(
            "lease-1:6Y", "6Y", ReserveBasis.PER_MONTH, 500,
            date(2027, 1, 31), 0,
        )
        lease = LeaseContract(
            "lease-1", "Airline", date(2027, 2, 1), date(2027, 2, 28),
            (account,), redelivery_conditions=(RedeliveryConditionRule("6Y", "0.5"),),
        )
        regime = UtilizationRegime(
            "use", "lease-1", lease.start_date, lease.end_date, 0, 0
        )
        result = build_lifecycle_settlement(self.scenario(component, lease, (regime,)))
        self.assertEqual(result.events.iloc[0]["date"], lease.end_date)
        self.assertEqual(result.component_states.iloc[0]["remaining_ratio"], Decimal("1"))
        self.assertEqual(result.redelivery.iloc[0]["gross_compensation"], Decimal("0"))

    def test_before_expiry_cutoff_collects_final_day_and_settles_event(self) -> None:
        component = self.usage_component(31)
        lease = LeaseContract(
            "lease-1", "Airline", date(2027, 1, 1), date(2027, 1, 31),
            (self.account(10),),
        )
        regime = UtilizationRegime(
            "use", "lease-1", lease.start_date, lease.end_date, 31, 10
        )
        known = KnownState(
            date(2027, 1, 30), 30, 10,
            component_usage_since_event={"E1": 30},
            reserve_account_balances={"lease-1:E1": 300},
        )
        result = build_lifecycle_settlement(
            self.scenario(
                component, lease, (regime,), analysis_date=lease.end_date,
                cutoff=CutoffPosition.BEFORE_EXPIRY_SETTLEMENT, known_state=known,
            )
        )
        ledger = result.reserve_ledger.iloc[0]
        event = result.events.iloc[0]
        self.assertEqual(ledger["reserve_inflow"], Decimal("10"))
        self.assertEqual(event["available_reserve"], Decimal("310"))
        self.assertEqual(event["date"], lease.end_date)


if __name__ == "__main__":
    unittest.main()
