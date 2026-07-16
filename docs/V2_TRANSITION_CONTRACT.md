# V2.4 Transition and Alternative Contract

A transition is an explicit lifecycle segment between leases. Its utilization regime controls FH and FC; its economic assumptions control owner outflows.

## Transition costs

Each transition can contain:

- an actual-day monthly cost for storage or continuing preparation;
- a fixed cost at transition commencement; and
- any number of dated, categorized costs such as ferry, maintenance, remarketing or delivery.

All amounts are positive owner outflows. `build_transition_cashflows()` preserves monthly, fixed and explicit values separately. `build_lifecycle_economics()` combines them with rent, reserves, maintenance, redelivery and refunds without changing the reserve accounting ledger.

## Alternatives

A `ScenarioAlternative` contains one complete scenario, not a partial override. Consequently each alternative may independently specify:

- follow-on lease start and end dates;
- utilization regimes;
- rent and reserve terms;
- transition length and costs;
- maintenance timing and redelivery conditions; and
- terminal horizon assumptions.

An `AlternativeSet` requires at least two unique alternatives for the same physical asset, currency and valuation date. Lease duration is date-driven and may be any number of days or months.
