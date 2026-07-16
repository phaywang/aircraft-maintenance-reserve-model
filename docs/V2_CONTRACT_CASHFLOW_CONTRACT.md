# V2.2 Contract Cash-Flow Contract

V2.2 calculates lease rent and maintenance-reserve inflows. It does not yet calculate maintenance reimbursement, redelivery compensation or account close-out.

## Ownership of assumptions

- Monthly rent, rent escalation and fixed-charge proration belong to `LeaseContract`.
- Each `ReserveAccountRule` maps one physical component to one contract-specific account.
- Reserve basis, rate, rate base date and escalation belong to that account, not to the aircraft component.
- The same physical component can therefore have different reserve terms in consecutive leases.

## Period treatment

Contract periods follow calendar months and retain arbitrary first and final stubs. Actual-day proration uses modeled days divided by calendar days. Full-month and no-proration conventions charge one complete fixed amount for any modeled portion of a contract month.

Rent and per-month reserves use the fixed-charge factor. FH and FC reserves use the V2.1 utilization occurring in that period. Rates follow the verified January-reset annual escalation convention.

The cash-ledger date is the period end. The contractual due date remains a separate audit field. This ensures the final lease period is collected inside the expiry-period sequence even when its contractual due day falls later in the calendar month.

## Outputs

`build_contract_cashflows()` returns:

- `periods`: one row per lease period with rent, total maintenance-reserve inflow and total contractual inflow;
- `reserve_accounts`: one row per lease period and component account with basis, rate, units and inflow.

Both tables use stable documented column orders. Rent appears only in the period summary and is therefore never duplicated across component-account rows.

## Cut-off treatment

When a known state is supplied, cash-flow calculation begins on the following day. Actual-day fixed amounts and usage-based reserves use only the remaining modeled portion. Under a full-month convention, any modeled portion retains one complete fixed charge.

## Validation

The engine rejects a reserve account without a basis or base date, negative rates and escalation, unknown component mappings, duplicated accounts and uncovered utilization days.
