# V2 Multi-Lease Lifecycle Plan

V2 extends the verified single-lease reserve model into a dated aircraft lifecycle engine. V1 remains frozen on `main`; V2 development proceeds on a separate branch and retains deterministic, component-level auditability.

## Objective

The completed model will evaluate an aircraft at any analysis date, carry its technical state across arbitrary leases and transition periods, and compare alternatives on the same valuation date and economic horizon. Lease terms are defined by actual dates rather than fixed three- or four-year branches.

## Mandatory expiry-period sequence

An active lease-expiry period is processed in this order:

1. apply flight hours and cycles;
2. collect rent and component maintenance reserves;
3. detect maintenance events;
4. record cost, reimbursement and unfunded exposure by component;
5. update post-maintenance technical state;
6. settle redelivery condition;
7. apply contract-specific refund, retention and offset rules;
8. close lease cash accounts;
9. carry the aircraft and component state into the next segment.

The final period may therefore contain both reserve inflow and maintenance outflow.

## Stages

| Stage | Deliverable |
|---|---|
| V2.0 | Lifecycle schema, cut-off semantics and V1 migration |
| V2.1 | Dated and variable utilization regimes |
| V2.2 | Arbitrary multi-lease contractual cash flows |
| V2.3 | Redelivery and end-of-lease settlement |
| V2.4 | Transition and follow-on alternatives |
| V2.5 | Common-horizon valuation and incremental NPV |
| V2.6 | Scenario comparison dashboard |
| V2.7 | Deterministic conclusions and optional LLM explanation |
| V2.8 | Sensitivity and uncertainty |

## Stage gates

Each stage must have explicit input contracts, deterministic output tables, validation rules, regression tests and an implementation record before the next stage begins. Calculation logic is completed before its dashboard layer.

## Deferred scope

Tax, debt waterfalls, portfolio fleet allocation, automated market-data ingestion and probabilistic credit/default modelling remain outside the core lifecycle engine.
