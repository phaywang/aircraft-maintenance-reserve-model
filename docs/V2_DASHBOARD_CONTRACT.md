# V2.6 Scenario Dashboard Contract

The V2 workspace is independent of the released V1 interface. V1 remains the detailed single-lease reserve model; V2 presents complete multi-lease lifecycle alternatives.

## Views

1. Decision summary — common-horizon NPV and major drivers.
2. Alternatives — arbitrary follow-on end date, rent, FH, FC, discount rate and baseline.
3. Utilization — continuous segment and regime timeline with TTSN/TCSN.
4. Events and settlement — maintenance funding, reserve reimbursement and redelivery.
5. Cash flow and valuation — owner cash-flow schedule, terminal value and incremental NPV.
6. Model audit — calculation scope and mandatory expiry sequence.

## Recalculation

The local `Run comparison` action posts the complete editable alternative set to `/api/v2/runs`. Python rebuilds every downstream table; the browser does not calculate financial results. GitHub Pages uses the same precomputed payload and clearly remains a demonstration.

## Deployment

- Local runtime: `/v2/` served by the Python dashboard API.
- GitHub Pages: `docs/v2/` with synchronized HTML, CSS, JavaScript and payload.
- V1 remains at the root URL.
