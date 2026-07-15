# Aircraft Maintenance Reserve Cash Flow

A deterministic Python model and local dashboard for forecasting aircraft utilization, maintenance events, maintenance reserve collections, reimbursements, component balances and funding shortfalls.

## What the model does

The model calculates a complete monthly history from manufacture through lease expiry and exposes the forecast from the selected analysis date.

1. **Utilization** — monthly flight hours and cycles roll into TTSN and TCSN.
2. **Maintenance events** — calendar, flight-hour and flight-cycle thresholds determine event months.
3. **Reserve collections** — component rates, charging bases and escalation produce monthly inflows.
4. **Settlement** — each event is reimbursed by the lower of its qualifying cost and the matching component reserve available.
5. **Adequacy** — component-level balances and shortfalls identify funding exposure.

Reserve accounts remain segregated throughout the model. The expiry month is processed as an active contractual period: final utilization and reserve collections occur before maintenance settlement and account close-out.

## Dashboard

The local dashboard provides editable inputs and eight analysis views:

- Overview
- Inputs & Assumptions
- Utilization
- Maintenance Events
- Reserve Inflow
- Event Settlement
- Reserve Adequacy
- Model Validation

## Demonstration assumptions

The included narrowbody scenario is fully illustrative and is not a market benchmark. It uses:

- manufacture and lease commencement: 30 June 2017;
- analysis date: 30 June 2026;
- lease expiry: 30 June 2029;
- monthly utilization: 260 flight hours and 95 flight cycles;
- five tracked accounts: 6Y, 12Y, landing gear, engine 1 and engine 2.

All dates, utilization, costs, reserve rates and escalation assumptions can be edited in the dashboard.

## Run locally

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python3 scripts/run_dashboard_api.py --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

On macOS, `Run Aircraft Reserve Dashboard.command` starts the same local service.

## Command-line outputs

```bash
python3 scripts/run_case.py --step 1
python3 scripts/run_case.py --step 2
python3 scripts/run_case.py --step 3
python3 scripts/run_case.py --step 4
```

CSV outputs are written to `outputs/`.

## Validation

The model runs 4,925 runtime assertions across 145 lease-period months and five component accounts. The default scenario is also checked against a versioned regression snapshot covering 257 calculation rows.

Run the test suite:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The tests cover threshold crossing, calendar-versus-usage event behavior, rate escalation, component segregation, lower-of reimbursement, balance continuity, expiry-period reserve collection and JSON/API contracts.

## Project structure

```text
src/aircraft_cashflow/   Calculation engine and local API
dashboard/static/        Dashboard application
tests/                   Unit, regression and interface tests
scripts/                 CLI and payload utilities
docs/images/             Dashboard screenshots
```

## Roadmap

The next model layer will support arbitrary analysis dates, variable utilization regimes, multiple leases, transition periods, redelivery settlement and common-horizon scenario valuation.

## License

MIT License. See [LICENSE](LICENSE).
