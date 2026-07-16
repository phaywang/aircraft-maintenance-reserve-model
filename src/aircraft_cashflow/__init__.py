"""Aircraft maintenance reserve cash-flow engine."""

from .config import build_default_case
from .balances import (
    build_forecast_reserve_balances,
    build_full_reserve_balances,
    escalated_event_cost,
)
from .events import (
    build_forecast_maintenance_calendar,
    build_full_maintenance_calendar,
)
from .inflows import (
    build_forecast_reserve_inflows,
    build_full_reserve_inflows,
    escalated_reserve_rate,
)
from .models import (
    CaseInputs,
    ComponentConfig,
    EventDriver,
    ReserveBasis,
    UtilizationOverride,
)
from .lifecycle import (
    SCENARIO_SCHEMA_VERSION,
    AircraftAsset,
    AnalysisContext,
    ContractPeriod,
    CutoffPosition,
    KnownState,
    LeaseContract,
    ProrationConvention,
    ReserveAccountRule,
    Scenario,
    TerminalValue,
    TerminalValueBasis,
    TransitionPeriod,
    UtilizationPattern,
    UtilizationRegime,
    build_contract_periods,
    lifecycle_segments,
    migrate_v1_case,
    scenario_to_v1_case,
)
from .utilization import build_forecast_utilization, build_full_utilization
from .lifecycle_utilization import (
    LIFECYCLE_UTILIZATION_COLUMNS,
    build_forecast_lifecycle_utilization,
    build_lifecycle_utilization,
)
from .contracts import (
    LEASE_CASHFLOW_COLUMNS,
    RESERVE_ACCOUNT_INFLOW_COLUMNS,
    ContractCashflowResult,
    build_contract_cashflows,
)

__all__ = [
    "CaseInputs",
    "ComponentConfig",
    "EventDriver",
    "ReserveBasis",
    "UtilizationOverride",
    "SCENARIO_SCHEMA_VERSION",
    "AircraftAsset",
    "AnalysisContext",
    "ContractPeriod",
    "CutoffPosition",
    "KnownState",
    "LeaseContract",
    "ProrationConvention",
    "ReserveAccountRule",
    "Scenario",
    "TerminalValue",
    "TerminalValueBasis",
    "TransitionPeriod",
    "UtilizationPattern",
    "UtilizationRegime",
    "build_contract_periods",
    "lifecycle_segments",
    "migrate_v1_case",
    "scenario_to_v1_case",
    "LIFECYCLE_UTILIZATION_COLUMNS",
    "build_forecast_lifecycle_utilization",
    "build_lifecycle_utilization",
    "LEASE_CASHFLOW_COLUMNS",
    "RESERVE_ACCOUNT_INFLOW_COLUMNS",
    "ContractCashflowResult",
    "build_contract_cashflows",
    "build_default_case",
    "build_forecast_reserve_balances",
    "build_forecast_maintenance_calendar",
    "build_forecast_reserve_inflows",
    "build_forecast_utilization",
    "build_full_maintenance_calendar",
    "build_full_reserve_balances",
    "build_full_reserve_inflows",
    "build_full_utilization",
    "escalated_reserve_rate",
    "escalated_event_cost",
]

__version__ = "2.0.0a0"
