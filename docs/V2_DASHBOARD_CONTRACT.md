# V2.1 Lessor Scenario Builder Dashboard Contract

The V2 workspace is independent of V1. V1 remains the detailed recruitment-case
reserve model at `/`; V2 is the lessor lifecycle scenario builder at `/v2/`.

## Views

1. Aircraft position — scenario identity, analysis date and authoritative known state.
2. Lease timeline — arbitrary lease and transition segments.
3. Forecast overview — reserve collections, event funding and exposure.
4. Maintenance funding — event cost, reserve reimbursement, lessee unfunded and off-lease cost.
5. Reserve accounts — lease-component roll-forward and close-out.
6. Reserve cash flow — dated reserve inflow, reimbursement, refund and balance ledger.
7. Scenario comparison — optional comparison of any number of independent scenarios.
8. Model audit — calculation scope and mandatory expiry sequence.

## Recalculation

`Run forecast` posts one complete scenario to `/api/v2/runs`. Python validates
and rebuilds every downstream table. The browser performs no financial or
maintenance calculations. `/api/v2/compare` accepts two or more independent
scenario payloads and returns reserve-funding summary metrics without mutating them.

Rent is deliberately outside the V2 dashboard scope. No rent input is required,
and no rent collection or whole-aircraft investment return is presented.

## Deployment

- Local runtime: `/v2/` served by the Python dashboard API.
- Static demonstration: embedded deterministic payload.
- V1 remains at the root URL and is not changed by V2.
