"""Command-line entry point for the local calculation engine."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .config import build_default_case
from .balances import build_forecast_reserve_balances
from .events import build_forecast_maintenance_calendar
from .export import (
    write_maintenance_calendar_csv,
    write_reserve_balances_csv,
    write_reserve_inflows_csv,
    write_utilization_csv,
)
from .inflows import build_forecast_reserve_inflows
from .utilization import build_forecast_utilization


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aircraft maintenance reserve cash-flow model"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--show-config",
        action="store_true",
        help="print the complete validated default configuration",
    )
    mode.add_argument(
        "--step",
        type=int,
        choices=(1, 2, 3, 4),
        help="run one implemented case step",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs"),
        help="directory for calculation outputs (default: outputs)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    case = build_default_case()
    if args.step == 4:
        balances = build_forecast_reserve_balances(case)
        output_path = write_reserve_balances_csv(
            balances, args.output_dir / "step4_reserve_balances.csv"
        )
        event_rows = balances.loc[
            balances["total_reserve_outflow"] > 0,
            ["date", "mx_calendar", "total_reserve_outflow", "total_unfunded_amount"],
        ]
        payload = {
            "step": 4,
            "rows": len(balances),
            "event_months": [
                {
                    "date": row.date.isoformat(),
                    "events": row.mx_calendar,
                    "outflow": str(row.total_reserve_outflow),
                    "unfunded": str(row.total_unfunded_amount),
                }
                for row in event_rows.itertuples(index=False)
            ],
            "lease_end_total_balance": str(
                balances.iloc[-1]["total_closing_balance"]
            ),
            "output": str(output_path.resolve()),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.step == 3:
        inflows = build_forecast_reserve_inflows(case)
        output_path = write_reserve_inflows_csv(
            inflows, args.output_dir / "step3_reserve_inflows.csv"
        )
        first = inflows.iloc[0]
        last = inflows.iloc[-1]
        payload = {
            "step": 3,
            "rows": len(inflows),
            "start_date": first["date"].isoformat(),
            "start_total_reserve_inflow": str(first["total_reserve_inflow"]),
            "end_date": last["date"].isoformat(),
            "end_total_reserve_inflow": str(last["total_reserve_inflow"]),
            "output": str(output_path.resolve()),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.step == 2:
        calendar = build_forecast_maintenance_calendar(case)
        output_path = write_maintenance_calendar_csv(
            calendar, args.output_dir / "step2_maintenance_calendar.csv"
        )
        events = calendar.loc[calendar["mx_calendar"] != "-", ["date", "mx_calendar"]]
        payload = {
            "step": 2,
            "rows": len(calendar),
            "event_months": [
                {"date": row.date.isoformat(), "events": row.mx_calendar}
                for row in events.itertuples(index=False)
            ],
            "output": str(output_path.resolve()),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.step == 1:
        utilization = build_forecast_utilization(case)
        output_path = write_utilization_csv(
            utilization, args.output_dir / "step1_utilization.csv"
        )
        first = utilization.iloc[0]
        last = utilization.iloc[-1]
        payload = {
            "step": 1,
            "rows": len(utilization),
            "start_date": first["date"].isoformat(),
            "end_date": last["date"].isoformat(),
            "start_ttsn": str(first["ttsn"]),
            "start_tcsn": str(first["tcsn"]),
            "end_ttsn": str(last["ttsn"]),
            "end_tcsn": str(last["tcsn"]),
            "output": str(output_path.resolve()),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    payload = case.to_dict() if args.show_config else case.summary()
    print(json.dumps(payload, indent=2, sort_keys=True))
    if not args.show_config:
        print(
            "Configuration only. Use --step 1, --step 2, --step 3, or --step 4 "
            "to run an implemented stage."
        )
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
