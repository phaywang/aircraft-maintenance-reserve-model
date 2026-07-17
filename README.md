# Aircraft Maintenance Reserve Lifecycle Model

A deterministic Python forecasting system for aircraft utilization, maintenance
events, maintenance reserve collections, reimbursements, component balances and
funding exposure. The project deliberately retains two workspaces: V1 is the
verified single-lease reference model, while V2 extends the same reserve
methodology to flexible multi-lease lifecycle scenarios.

## Start here

This model is designed for a lessor, aircraft owner or technical-finance adviser
reviewing one practical question:

> Will the component-specific maintenance reserves available at each forecast
> maintenance event be sufficient to reimburse the modeled event cost, and how
> does that exposure change under a different lease path?

The calculation workflow is:

1. Enter the aircraft position, maintenance program and contractual reserve terms.
2. Enter one lease in V1, or any number of consecutive leases in V2.
3. Select **Run model**. The Python engine reconstructs history, calculates the
   analysis-date opening position and forecasts every subsequent month.
4. Review event funding first, then trace each result through component reserve
   accounts and the monthly cash ledger.
5. Optionally use **Analysis & Q&A** to turn the validated results into an English
   report or ask a focused lessor-side question.

For a two-minute review, open the hosted V1 dashboard and follow views 01–09.
Then open V2 to see how the same calculation extends across consecutive leases
and multiple independently calculated scenarios. The hosted dashboards contain
precalculated demonstration data; run the project locally to edit assumptions
and recalculate.

## Choose a workspace

| Workspace | Purpose | Best for | Hosted dashboard |
|---|---|---|---|
| **Reference model (V1)** | Verified monthly single-lease model with a complete calculation audit trail | Reviewing the methodology, assumptions and component-level roll-forward | [Open V1](https://phaywang.github.io/aircraft-maintenance-reserve-model/) |
| **Lifecycle scenarios (V2)** | Flexible analysis-date and multi-lease forecasting for a lessor or aircraft owner | Building future lease paths and assessing maintenance funding exposure | [Open V2](https://phaywang.github.io/aircraft-maintenance-reserve-model/v2/) |

V2 does not replace V1. A V2 scenario containing only the reference lease is
reconciled to the V1 opening position, event funding, reserve-account
roll-forward and monthly component cash flow. Both hosted workspaces are
read-only demonstrations; clone the repository to recalculate edited inputs.

## Product walkthrough

### 1. Establish the single-lease reference position

V1 starts with the aircraft, analysis date, remaining lease term and headline
maintenance-reserve position. The opening reserve is reconstructed from the
modeled history rather than entered as an unexplained balancing figure.

![V1 dashboard overview](docs/assets/demo/v1-overview.png)

### 2. Trace every event to its component account

The event-settlement view compares the escalated event cost with the reserve
available in the matching 6Y, 12Y, landing-gear or engine account. Aggregate
cash flow remains available for reconciliation, while component-level balances
show which contractual rate may require review.

![V1 component event settlement](docs/assets/demo/v1-event-settlement.png)

### 3. Interpret validated results

The optional analysis workspace can generate a structured report or answer a
free-form question. Financial statements are bound to deterministic evidence;
the language model cannot create a second set of cash-flow calculations.

![V1 evidence-grounded analysis](docs/assets/demo/v1-question-result.png)

### 4. Extend the same aircraft across consecutive leases

V2 carries the physical aircraft state, TTSN, TCSN and component usage across
lease boundaries. Each lease can have different utilization and reserve terms,
while its contractual component accounts open and close separately.

![V2 consecutive lease timeline](docs/assets/demo/v2-lease-timeline.png)

### 5. Compare independently calculated lifecycle paths

Users may duplicate a lifecycle path, change lease duration, utilization or
reserve terms, run each scenario independently and select any number for
comparison. The dashboard reports absolute outcomes and timing trade-offs; it
does not declare a universal winner from an incomplete economic scope.

![V2 multi-scenario comparison](docs/assets/demo/v2-scenario-comparison.png)

### 6. Generate cross-scenario analysis

The V2 analysis workspace can explain the active scenario or a selected
comparison set, including the relationship between top-up exposure, event
timing, retained reserves and remaining component life.

![V2 cross-scenario analysis](docs/assets/demo/v2-cross-scenario-question.png)

For the complete 01–09 presentation sequence, demonstration inputs, suggested
questions and full-page screenshot index, open the
[product demo workflow](docs/DEMO_WORKFLOW.md).

## What the model does

The model calculates a complete monthly history from manufacture through lease expiry and exposes the forecast from the selected analysis date.

1. **Utilization** — monthly flight hours and cycles roll into TTSN and TCSN.
2. **Maintenance events** — calendar, flight-hour and flight-cycle thresholds determine event months.
3. **Reserve collections** — component rates, charging bases and escalation produce monthly inflows.
4. **Settlement** — each event is reimbursed by the lower of its qualifying cost and the matching component reserve available.
5. **Adequacy** — component-level balances and shortfalls identify funding exposure.

Reserve accounts remain segregated throughout the model. The expiry month is processed as an active contractual period: final utilization and reserve collections occur before maintenance settlement and account close-out.

### How to read the principal outputs

| Output | Meaning in this model |
|---|---|
| **MR collected** | Contractual maintenance reserve inflow credited to the matching component account |
| **Event cost** | Escalated modeled maintenance cost at the event date |
| **Reserve reimbursement** | Lower of event cost and the matching reserve available at settlement |
| **Lessee top-up** | Modeled unfunded contractual obligation; it is not assumed to be collected cash |
| **Retained reserve** | Balance remaining after modeled settlement and lease close-out, subject to the stated close-out assumption |

The model does not net one component account against another. Base rent, aircraft
market value, NPV, downtime and lessee credit or collectability remain outside
the active scope.

## Workspace design

V1 follows the original calculation sequence through nine views: overview,
inputs and assumptions, utilization, maintenance events, reserve inflow, event
settlement, reserve adequacy, Analysis & Q&A and model validation. The optional
analysis workspace can generate a structured English report or answer a
user-defined question from the current validated model results.

V2 uses the same reserve logic in a lifecycle workflow:

1. Aircraft position and editable maintenance program.
2. Any number of consecutive lease contracts and their utilization and reserve terms.
3. Current-scenario forecast overview, event funding, reserve accounts and detailed cash flow.
4. Optional comparison of any number of independently calculated scenarios.
5. Optional Bedrock-assisted English reports and evidence-grounded Q&A.
6. Model audit and calculation provenance.

The physical aircraft state continues across lease boundaries. Each lease has
separate component reserve accounts, and the expiry period is processed in the
required order: final utilization, final reserve collection, maintenance-event
settlement and then account close-out.

## Demonstration assumptions

The included narrowbody scenario is fully illustrative and is not a market benchmark. It uses:

- aircraft / lessee: A320-200 operated by the fictional AeroVista Airlines;
- manufacture and lease commencement: 30 June 2017;
- analysis date: 30 June 2026;
- lease expiry: 30 June 2029;
- monthly utilization: 260 flight hours and 95 flight cycles;
- five tracked accounts: 6Y, 12Y, landing gear, engine 1 and engine 2.

All dates, utilization, costs, reserve rates and escalation assumptions can be edited in the dashboard.

The synthetic reserve rates are calibrated to demonstrate different funding outcomes: fully funded events, a near-threshold event and material component shortfalls. They are illustrative inputs, not market quotations.

The public demonstration uses a synthetic timeline, fictional counterparties
and illustrative commercial assumptions. Calendar-year escalation resets each
January, so all displayed balances and funding outcomes are recalculated from
the published inputs rather than presented as fixed examples.

The V2 public demo starts from the same aircraft and analysis-date position. It
then continues the existing lease through 30 June 2029 and adds a consecutive
follow-on lease with the fictional Northstar Air from 1 July 2029 through
31 January 2032. The follow-on path uses 250 FH and 95 FC per month and opens new
component reserve accounts using a 1.05 rate multiplier. These terms are chosen
to demonstrate the lifecycle workflow, not to represent a market quotation.

## Run locally

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python3 scripts/run_dashboard_api.py --port 8765
```

Open [V1 at http://127.0.0.1:8765](http://127.0.0.1:8765) or
[V2 at http://127.0.0.1:8765/v2/](http://127.0.0.1:8765/v2/). Both dashboards
also provide the same workspace switcher at the top of the page.

On macOS, `Run Aircraft Reserve Dashboard.command` starts the same local service.

## Bedrock-assisted analysis

V1 can generate a full maintenance-reserve report, a focused funding or
component-rate review, an engine sensitivity note, or an answer to a custom
analysis question. V2 can generate a `Current Scenario Analysis`, a
`Cross-Scenario Decision Report`, or answer a custom question about either the
active scenario or selected comparison set. Both workspaces use AWS Bedrock, while the deterministic
Python engine remains authoritative: Bedrock receives a compact evidence packet
and interprets verified results from a lessor perspective. It does not
recalculate cash flows or introduce rent, NPV, aircraft value, downtime or
credit-risk assumptions.

For the V1 engine-interval sensitivity analysis, the Python engine freezes historical events and the
analysis-date opening reserve, then recalculates only the next E1 event using
95%, 100% and 105% of the base flight-hour interval. The resulting “advantage”
is explicitly limited to the lessor's modeled maintenance-reserve reimbursement
cash outflow; broader technical and asset-value effects remain outside V1.

Install the optional dependencies and create a local `.env` file:

```bash
pip install -e '.[llm]'
cp .env.example .env
```

```text
AWS_PROFILE=your-local-profile
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6
```

Start the local service and open V1 `08 Analysis & Q&A`, or run the required V2
scenario(s) and open V2 `08 Analysis & Q&A`. All prompts and generated reports are English. Every
currency amount and percentage in published prose must match a deterministic
claim and carry a verified source binding. One model repair is attempted; any
remaining unsupported financial lines are removed before publication.

The GitHub Pages dashboard is static and cannot call a private AWS account. The
Bedrock report feature is therefore available only through the local service or
another explicitly configured backend deployment. AWS credentials and `.env`
are excluded from Git.

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
src/aircraft_cashflow/llm/  Bedrock client, prompts and report guardrails
dashboard/static/        Dashboard application
dashboard/v2/            V2 lessor lifecycle scenario builder
tests/                   Unit, regression and interface tests
scripts/                 CLI and payload utilities
docs/v2/                 GitHub Pages V2 application
docs/assets/             Dashboard screenshots and demo assets
```

## V2 lifecycle model

Version 2.2 keeps V1 as the verified reference baseline and provides an independent
lessor lifecycle scenario builder. V1 changes are limited to verified bug fixes;
V2 is the active product-development workspace. One V2 scenario can start at an
arbitrary analysis date and contain a current lease plus any number of
consecutive future leases. Physical component state continues across leases
while contract reserve accounts close separately.

The primary output covers maintenance-reserve collections, event cost, reserve
reimbursement, lessee top-up exposure and lease-end reserve close-out. Rent,
transition-period assumptions and whole-aircraft investment returns are outside
the active dashboard; multi-scenario comparison is optional and does not impose
an automatic ranking.

The optional advisory layer adds English narrative interpretation without
changing any deterministic result. V1 supports structured reports and
current-run Q&A with suggested questions for common reserve-review tasks. If a
question requires changed assumptions, the user must edit the inputs and rerun
the deterministic model. V2 current-scenario reports and questions explain one
lifecycle path, while cross-scenario reports and questions explain absolute
outcomes and trade-offs across any selected set of calculated scenarios.

## License

MIT License. See [LICENSE](LICENSE).
