"""V2.2 multi-lease rent and maintenance-reserve cash-flow tests."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from aircraft_cashflow.config import build_default_case
from aircraft_cashflow.contracts import (
    LEASE_CASHFLOW_COLUMNS,
    RESERVE_ACCOUNT_INFLOW_COLUMNS,
    build_contract_cashflows,
)
from aircraft_cashflow.lifecycle import (
    CutoffPosition,
    KnownState,
    LeaseContract,
    ProrationConvention,
    ReserveAccountRule,
    Scenario,
    TransitionPeriod,
    UtilizationRegime,
    migrate_v1_case,
)
from aircraft_cashflow.models import ReserveBasis


class ContractCashflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.asset = migrate_v1_case(build_default_case()).asset

    def account(
        self,
        account_id: str,
        component_code: str,
        basis: ReserveBasis,
        rate: int | str,
        base_date: date,
        escalation: str = "0",
    ) -> ReserveAccountRule:
        return ReserveAccountRule(
            account_id,
            component_code,
            basis,
            rate,
            base_date,
            escalation,
        )

    def scenario(
        self,
        *,
        leases: tuple[LeaseContract, ...],
        regimes: tuple[UtilizationRegime, ...],
        analysis_date: date,
        horizon: date,
        transitions: tuple[TransitionPeriod, ...] = (),
        known_state: KnownState | None = None,
    ) -> Scenario:
        return Scenario(
            "contract-cashflow-test",
            "Contract cashflow test",
            self.asset,
            analysis_date,
            CutoffPosition.AFTER_EXPIRY_SETTLEMENT,
            analysis_date,
            horizon,
            leases,
            regimes,
            transitions,
            known_state=known_state,
        )

    def test_actual_day_stub_rent_and_reserves_reconcile(self) -> None:
        start = date(2027, 1, 15)
        end = date(2027, 3, 10)
        accounts = (
            self.account("lease-1:6Y", "6Y", ReserveBasis.PER_MONTH, 3100, start),
            self.account("lease-1:E1", "E1", ReserveBasis.PER_FLIGHT_HOUR, 10, start),
        )
        lease = LeaseContract(
            "lease-1", "Airline", start, end, accounts,
            ProrationConvention.ACTUAL_DAYS, monthly_rent=31000,
        )
        regime = UtilizationRegime("use", "lease-1", start, end, 310, 155)
        result = build_contract_cashflows(
            self.scenario(
                leases=(lease,), regimes=(regime,), analysis_date=date(2027, 2, 28), horizon=end
            )
        )
        self.assertEqual(tuple(result.periods.columns), LEASE_CASHFLOW_COLUMNS)
        self.assertEqual(tuple(result.reserve_accounts.columns), RESERVE_ACCOUNT_INFLOW_COLUMNS)
        self.assertEqual(
            list(result.periods["rent_inflow"]),
            [Decimal("17000"), Decimal("31000"), Decimal("10000")],
        )
        self.assertEqual(
            list(result.periods["flight_hours"]),
            [Decimal("170"), Decimal("310"), Decimal("100")],
        )
        self.assertEqual(
            list(result.periods["maintenance_reserve_inflow"]),
            [Decimal("3400"), Decimal("6200"), Decimal("2000")],
        )
        self.assertTrue(result.periods.iloc[-1]["is_expiry_period"])
        self.assertEqual(result.periods.iloc[-1]["date"], end)

    def test_full_month_convention_charges_one_amount_despite_analysis_split(self) -> None:
        start = date(2027, 1, 1)
        end = date(2027, 1, 31)
        accounts = (
            self.account("lease-1:6Y", "6Y", ReserveBasis.PER_MONTH, 1000, start),
        )
        lease = LeaseContract(
            "lease-1", "Airline", start, end, accounts,
            ProrationConvention.FULL_MONTH, monthly_rent=10000,
        )
        regime = UtilizationRegime("use", "lease-1", start, end, 310, 155)
        result = build_contract_cashflows(
            self.scenario(
                leases=(lease,), regimes=(regime,), analysis_date=date(2027, 1, 15), horizon=end
            )
        )
        self.assertEqual(len(result.periods), 1)
        self.assertEqual(result.periods.iloc[0]["rent_inflow"], Decimal("10000"))
        self.assertEqual(
            result.periods.iloc[0]["maintenance_reserve_inflow"], Decimal("1000")
        )

    def test_known_state_calculates_only_remaining_period_usage(self) -> None:
        start = date(2027, 1, 1)
        end = date(2027, 3, 31)
        accounts = (
            self.account("lease-1:E1", "E1", ReserveBasis.PER_FLIGHT_HOUR, 10, start),
        )
        lease = LeaseContract(
            "lease-1", "Airline", start, end, accounts,
            ProrationConvention.ACTUAL_DAYS, monthly_rent=28000,
        )
        regime = UtilizationRegime("use", "lease-1", start, end, 280, 140)
        state = KnownState(date(2027, 2, 15), 10000, 5000)
        result = build_contract_cashflows(
            self.scenario(
                leases=(lease,), regimes=(regime,), analysis_date=state.as_of_date,
                horizon=end, known_state=state,
            )
        )
        self.assertEqual(list(result.periods["date"]), [date(2027, 2, 28), end])
        self.assertEqual(result.periods.iloc[0]["flight_hours"], Decimal("130"))
        self.assertEqual(result.periods.iloc[0]["rent_inflow"], Decimal("13000"))
        self.assertEqual(
            result.periods.iloc[0]["maintenance_reserve_inflow"], Decimal("1300")
        )

    def test_separate_leases_use_separate_contract_terms(self) -> None:
        lease_1 = LeaseContract(
            "lease-1", "Airline A", date(2027, 1, 1), date(2027, 1, 31),
            (self.account("lease-1:E1", "E1", ReserveBasis.PER_FLIGHT_HOUR, 10, date(2027, 1, 1)),),
            monthly_rent=10000,
        )
        transition = TransitionPeriod(
            "transition", date(2027, 2, 1), date(2027, 2, 28), "Storage"
        )
        lease_2 = LeaseContract(
            "lease-2", "Airline B", date(2027, 3, 1), date(2027, 3, 31),
            (self.account("lease-2:E1", "E1", ReserveBasis.PER_FLIGHT_HOUR, 20, date(2027, 3, 1)),),
            monthly_rent=20000,
        )
        regimes = (
            UtilizationRegime("use-1", "lease-1", lease_1.start_date, lease_1.end_date, 310, 155),
            UtilizationRegime("storage", "transition", transition.start_date, transition.end_date, 0, 0),
            UtilizationRegime("use-2", "lease-2", lease_2.start_date, lease_2.end_date, 620, 310),
        )
        result = build_contract_cashflows(
            self.scenario(
                leases=(lease_1, lease_2), transitions=(transition,), regimes=regimes,
                analysis_date=lease_1.end_date, horizon=lease_2.end_date,
            )
        )
        self.assertEqual(list(result.periods["lease_id"]), ["lease-1", "lease-2"])
        self.assertEqual(list(result.periods["rent_inflow"]), [Decimal("10000"), Decimal("20000")])
        self.assertEqual(
            list(result.periods["maintenance_reserve_inflow"]),
            [Decimal("3100"), Decimal("12400")],
        )

    def test_calendar_year_escalation_is_contract_specific(self) -> None:
        start = date(2027, 12, 1)
        end = date(2028, 1, 31)
        account = self.account(
            "lease-1:6Y", "6Y", ReserveBasis.PER_MONTH, 1000, start, "0.10"
        )
        lease = LeaseContract(
            "lease-1", "Airline", start, end, (account,),
            monthly_rent=10000, rent_base_date=start, annual_rent_escalation="0.05",
        )
        regime = UtilizationRegime("use", "lease-1", start, end, 310, 155)
        result = build_contract_cashflows(
            self.scenario(
                leases=(lease,), regimes=(regime,), analysis_date=date(2027, 12, 31), horizon=end
            )
        )
        self.assertEqual(list(result.periods["rent_rate"]), [Decimal("10000"), Decimal("10500.00")])
        self.assertEqual(
            list(result.periods["maintenance_reserve_inflow"]),
            [Decimal("1000"), Decimal("1100.00")],
        )

    def test_account_without_rate_terms_fails_clearly(self) -> None:
        start = date(2027, 1, 1)
        end = date(2027, 1, 31)
        lease = LeaseContract(
            "lease-1", "Airline", start, end,
            (ReserveAccountRule("lease-1:E1", "E1"),),
        )
        regime = UtilizationRegime("use", "lease-1", start, end, 310, 155)
        scenario = self.scenario(
            leases=(lease,), regimes=(regime,), analysis_date=end, horizon=end
        )
        with self.assertRaisesRegex(ValueError, "requires rate_base_date"):
            build_contract_cashflows(scenario)


if __name__ == "__main__":
    unittest.main()
