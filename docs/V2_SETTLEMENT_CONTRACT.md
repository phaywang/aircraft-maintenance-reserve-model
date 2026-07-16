# V2.3 Maintenance and Redelivery Settlement Contract

V2.3 separates physical aircraft maintenance from lease-specific reserve accounts. A component event belongs to the aircraft; the active lease determines whether an account is available to reimburse it.

## Maintenance events

- Calendar events use the component's last event date or aircraft manufacture date and retain end-of-month behavior.
- FH and FC events use usage since the last event and interpolate a deterministic event date inside the utilization slice.
- Multiple thresholds crossed in one slice create multiple events.
- Events during transitions remain physical costs but have no lease reserve account.

Event cost follows the component's cost base date and annual escalation. Reimbursement is the lower of available component-account reserve and event cost. The difference is reported as unfunded exposure.

## Expiry sequence

The final lease period is processed in this order:

1. apply final-period FH and FC;
2. collect rent and component reserves;
3. settle maintenance events and update component state;
4. calculate redelivery remaining-life compensation;
5. apply reserve refund, retention or redelivery offset;
6. close every lease reserve account.

A before-expiry-settlement cut-off requires known state through the preceding day. This preserves the final day's utilization, collection and maintenance.

## Redelivery condition

Each condition states a minimum remaining-life ratio for one component. Gross compensation equals the escalated reference event cost multiplied by the shortfall between required and actual remaining-life ratios. No charge arises when actual condition meets or exceeds the requirement.

## Account close-out

- `retain_by_lessor`: unused reserve remains with the lessor and the account closes.
- `refund_to_lessee`: unused reserve is a cash outflow to the lessee.
- `offset_redelivery`: reserve first offsets that component's redelivery compensation; any excess is refunded.

## Outputs

`build_lifecycle_settlement()` returns event settlement, component state, redelivery, reserve-account ledger and owner cash-flow tables. Owner net cash flow equals rent plus reserve collections plus net redelivery cash, less maintenance cost and reserve refunds.
