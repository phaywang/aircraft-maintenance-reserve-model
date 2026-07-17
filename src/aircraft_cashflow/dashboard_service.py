"""Dashboard data contract built only from the verified Stage 1-4 engine."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

import pandas as pd

from .audit import (
    build_input_changes,
    build_demo_reconciliation,
    build_runtime_checks,
)
from .balances import (
    available_balance_column,
    build_forecast_reserve_balances,
    build_full_reserve_balances,
    closing_balance_column,
    event_cost_column,
    opening_balance_column,
    reserve_outflow_column,
    unfunded_amount_column,
)
from .config import build_default_case
from .events import (
    build_forecast_maintenance_calendar,
    event_count_column,
)
from .inflows import build_forecast_reserve_inflows, reserve_inflow_column
from .models import (
    CaseInputs,
    ComponentConfig,
    EventDriver,
    ReserveBasis,
    UtilizationOverride,
)
from .utilization import build_forecast_utilization


def serialize_dashboard_value(value: Any) -> Any:
    """Convert model values to JSON-safe values without float conversion."""

    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {
            str(key): serialize_dashboard_value(item) for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [serialize_dashboard_value(item) for item in value]
    return value


def _date(value: object, field_name: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from exc


def case_from_payload(payload: dict[str, object]) -> CaseInputs:
    """Build validated typed inputs from the dashboard request contract."""

    if not payload:
        return build_default_case()
    required = {
        "aircraft_type",
        "date_of_manufacture",
        "lessee",
        "lease_start_date",
        "analysis_date",
        "lease_expiry_date",
        "default_monthly_fh",
        "default_monthly_fc",
        "components",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise ValueError("missing case fields: " + ", ".join(missing))

    manufacture_date = _date(
        payload["date_of_manufacture"], "date_of_manufacture"
    )
    lease_start_date = _date(payload["lease_start_date"], "lease_start_date")

    raw_components = payload["components"]
    if not isinstance(raw_components, list):
        raise ValueError("components must be an array")
    components: list[ComponentConfig] = []
    for index, raw in enumerate(raw_components):
        if not isinstance(raw, dict):
            raise ValueError(f"components[{index}] must be an object")
        try:
            components.append(
                ComponentConfig(
                    code=str(raw["code"]),
                    name=str(raw["name"]),
                    event_driver=EventDriver(str(raw["event_driver"])),
                    interval=raw["interval"],
                    base_cost=raw["base_cost"],
                    # V1 is a single-lease reference model: technical costs are
                    # manufacture-year values and contract rates commence with
                    # the lease. These dates are derived, not separate inputs.
                    cost_base_date=manufacture_date,
                    annual_cost_escalation=raw["annual_cost_escalation"],
                    reserve_basis=ReserveBasis(str(raw["reserve_basis"])),
                    base_reserve_rate=raw["base_reserve_rate"],
                    reserve_rate_base_date=lease_start_date,
                    annual_reserve_escalation=raw["annual_reserve_escalation"],
                    last_event_date=(
                        _date(
                            raw["last_event_date"],
                            f"components[{index}].last_event_date",
                        )
                        if raw.get("last_event_date") is not None
                        else None
                    ),
                    usage_since_event_at_lease_start=raw.get(
                        "usage_since_event_at_lease_start"
                    ),
                )
            )
        except KeyError as exc:
            raise ValueError(
                f"components[{index}] is missing field {exc.args[0]}"
            ) from exc

    raw_overrides = payload.get("utilization_overrides", [])
    if not isinstance(raw_overrides, list):
        raise ValueError("utilization_overrides must be an array")
    overrides: list[UtilizationOverride] = []
    for index, raw in enumerate(raw_overrides):
        if not isinstance(raw, dict):
            raise ValueError(f"utilization_overrides[{index}] must be an object")
        try:
            overrides.append(
                UtilizationOverride(
                    month_end=_date(
                        raw["month_end"],
                        f"utilization_overrides[{index}].month_end",
                    ),
                    flight_hours=raw["flight_hours"],
                    flight_cycles=raw["flight_cycles"],
                )
            )
        except KeyError as exc:
            raise ValueError(
                f"utilization_overrides[{index}] is missing field {exc.args[0]}"
            ) from exc

    return CaseInputs(
        aircraft_type=str(payload["aircraft_type"]),
        date_of_manufacture=manufacture_date,
        lessee=str(payload["lessee"]),
        lease_start_date=lease_start_date,
        analysis_date=_date(payload["analysis_date"], "analysis_date"),
        lease_expiry_date=_date(payload["lease_expiry_date"], "lease_expiry_date"),
        default_monthly_fh=payload["default_monthly_fh"],
        default_monthly_fc=payload["default_monthly_fc"],
        components=tuple(components),
        utilization_overrides=tuple(overrides),
    )


def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
    return [
        serialize_dashboard_value(record)
        for record in frame.to_dict(orient="records")
    ]


def _sum_decimal(values: object) -> Decimal:
    return sum((Decimal(str(value)) for value in values), Decimal("0"))


def _funding_events(
    balances: pd.DataFrame, case: CaseInputs
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for row in balances.itertuples(index=False):
        for component in case.components:
            code = component.code
            count = int(getattr(row, event_count_column(code)))
            if count == 0:
                continue
            cost = Decimal(str(getattr(row, event_cost_column(code))))
            available = Decimal(str(getattr(row, available_balance_column(code))))
            shortfall = Decimal(str(getattr(row, unfunded_amount_column(code))))
            events.append(
                serialize_dashboard_value(
                    {
                        "component": code,
                        "component_name": component.name,
                        "event_date": row.date,
                        "event_count": count,
                        "opening_reserve": Decimal(
                            str(getattr(row, opening_balance_column(code)))
                        ),
                        "current_inflow": Decimal(
                            str(getattr(row, reserve_inflow_column(code)))
                        ),
                        "event_cost": cost,
                        "available_reserve": available,
                        "reimbursement": Decimal(
                            str(getattr(row, reserve_outflow_column(code)))
                        ),
                        "shortfall": shortfall,
                        "coverage_ratio": available / cost if cost else None,
                        "fully_funded": shortfall == 0,
                        "closing_balance_after_event": Decimal(
                            str(getattr(row, closing_balance_column(code)))
                        ),
                    }
                )
            )
    return events


def run_dashboard_case(case: CaseInputs) -> dict[str, object]:
    """Run Stage 1-4 and return one typed dashboard payload."""

    utilization = build_forecast_utilization(case)
    calendar = build_forecast_maintenance_calendar(case)
    inflows = build_forecast_reserve_inflows(case)
    balances = build_forecast_reserve_balances(case)
    full_balances = build_full_reserve_balances(case)
    historical_columns = ["date", "mx_calendar"]
    for component in case.components:
        code = component.code
        historical_columns.extend(
            [
                opening_balance_column(code),
                f"reserve_inflow_{code}",
                reserve_outflow_column(code),
                closing_balance_column(code),
            ]
        )
    historical_columns.extend(
        ["total_reserve_inflow", "total_reserve_outflow", "total_closing_balance"]
    )
    opening_balance_history = full_balances.loc[
        (full_balances["date"] >= case.lease_start_date)
        & (full_balances["date"] < case.analysis_date),
        historical_columns,
    ].copy()
    historical_event_rows = full_balances.loc[
        (full_balances["date"] >= case.lease_start_date)
        & (full_balances["date"] < case.analysis_date)
    ].copy()
    historical_funding_events = _funding_events(historical_event_rows, case)
    funding_events = _funding_events(balances, case)
    demo_case = case.to_dict() == build_default_case().to_dict()
    demo_history = full_balances.loc[
        (full_balances["date"] >= case.lease_start_date)
        & (full_balances["date"] <= case.analysis_date)
    ].copy()
    runtime_checks = build_runtime_checks(full_balances, case)
    demo_reconciliation = build_demo_reconciliation(
        demo_case,
        {
            "stage_1": utilization,
            "stage_2": calendar,
            "stage_3": inflows,
            "stage_4_forecast": balances,
            "stage_4_history": demo_history,
        },
    )
    input_signature = hashlib.sha256(
        json.dumps(case.to_dict(), sort_keys=True).encode("utf-8")
    ).hexdigest()

    summary = {
        "forecast_reserve_inflow": _sum_decimal(
            balances["total_reserve_inflow"]
        ),
        "forecast_reimbursement": _sum_decimal(
            balances["total_reserve_outflow"]
        ),
        "forecast_shortfall": _sum_decimal(balances["total_unfunded_amount"]),
        "lease_end_reserve_balance": Decimal(
            str(balances.iloc[-1]["total_closing_balance"])
        ),
        "forecast_months": len(balances),
        "component_event_count": len(funding_events),
        "underfunded_event_count": sum(
            1 for event in funding_events if not event["fully_funded"]
        ),
    }
    payload = {
        "run": {
            "run_id": str(uuid4()),
            "status": (
                "validated"
                if all(check["passed"] for check in runtime_checks.values())
                else "failed"
            ),
            "calculated_at": datetime.now(timezone.utc),
            "model_version": "1.0.1-phase1",
            "demo_case": demo_case,
            "input_signature": input_signature,
        },
        "case": case.to_dict(),
        "summary": summary,
        "utilization": _records(utilization),
        "maintenance_calendar": _records(calendar),
        "reserve_inflows": _records(inflows),
        "opening_balance_history": _records(opening_balance_history),
        "historical_funding_events": historical_funding_events,
        "cashflows": _records(balances),
        "funding_events": funding_events,
        "audit": {
            "runtime_checks": runtime_checks,
            "runtime_scope": {
                "start_date": case.lease_start_date,
                "end_date": case.lease_expiry_date,
                "months": len(
                    full_balances.loc[
                        (full_balances["date"] >= case.lease_start_date)
                        & (full_balances["date"] <= case.lease_expiry_date)
                    ]
                ),
                "component_accounts": len(case.components),
            },
            "demo_reconciliation": demo_reconciliation,
            "input_changes": build_input_changes(case),
            "calculation_scope": ["stage_1", "stage_2", "stage_3", "stage_4"],
            "calculation_engine": "deterministic",
        },
    }
    return serialize_dashboard_value(payload)
