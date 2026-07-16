# V2 Scenario Builder Contract

## Product boundary

V1 remains the verified single-lease recruitment-case dashboard at `/`. V2 is
an independent lessor / aircraft-owner lifecycle forecast at `/v2/`. V2 never
changes V1 inputs, calculations, routes or static assets.

## Core workflow

One scenario is a complete planned path for one physical aircraft from an
arbitrary analysis date through a user-selected forecast end date. A scenario
may contain one current lease, any number of future leases and explicit
transition or storage periods. A scenario runs independently. Comparison is
optional and accepts two or more independently calculated scenarios.

The physical aircraft state is continuous across all segments. TTSN, TCSN and
component usage do not reset at a lease boundary. Contract reserve accounts are
lease-specific and close according to that lease's close-out rule.

## Analysis cut-off

The known state is authoritative at the analysis date and contains:

- TTSN and TCSN;
- component usage since the last event or last calendar event date;
- current-lease component reserve balances.

Forecast utilization starts on the following day. If the analysis date is a
lease expiry and settlement is pending, the final day is modeled before account
close-out.

## Required expiry sequence

1. Apply final-period FH and FC.
2. Collect final-period rent and component reserves.
3. Settle maintenance events against their matching component account.
4. Update physical component state.
5. Calculate redelivery condition compensation.
6. Refund, retain or offset unused reserve according to contract terms.
7. Close the lease accounts and continue the physical aircraft state.

## Lessor cash-flow convention

`event_cost` is the full escalated technical cost. `reserve_reimbursement` is
the lessor cash outflow and is capped at the matching available reserve.
`unfunded_amount` is paid by the lessee and is an exposure diagnostic, not a
lessor cash outflow.

For each dated row:

```
net_lessor_cashflow = rent_inflow
                    + maintenance_reserve_inflow
                    + redelivery_cash_inflow
                    - reserve_reimbursement_outflow
                    - reserve_refund_outflow
                    - transition_cost
```

For each reserve account:

```
closing_balance = opening_balance
                + reserve_inflow
                - reserve_reimbursement
                - redelivery_offset
                - refund_to_lessee
                - retained_by_lessor
```

## Primary outputs

The primary result is a nominal lifecycle forecast, not NPV:

- rent and maintenance reserve collections;
- maintenance event cost, reserve reimbursement and lessee unfunded amount;
- component reserve ledgers and lease close-out;
- redelivery compensation;
- transition and storage costs;
- dated net lessor cash flow;
- technical state at every lease expiry;
- maximum funding exposure and minimum dated cash flow.

Discounted valuation remains outside the core workflow and may be offered later
as an optional advanced analysis.

## Validation rules

- Lease and transition identifiers are unique.
- Lifecycle segments cannot overlap or contain implicit gaps.
- Every segment has a complete utilization regime, including zero-use downtime.
- Lease reserve accounts map one-to-one to physical maintenance components.
- Opening reserve balances may reference only the lease active at the cut-off.
- The forecast end must be covered by the final lifecycle segment.
- Adding or comparing another scenario cannot change an existing scenario run.
- Identical scenario inputs must produce identical deterministic tables.

