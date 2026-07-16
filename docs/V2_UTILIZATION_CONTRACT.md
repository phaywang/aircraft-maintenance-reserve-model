# V2.1 Utilization Contract

V2.1 converts dated aircraft-lifecycle assumptions into one deterministic FH/FC and TTSN/TCSN table. It calculates technical usage only; rent, maintenance reserves and redelivery cash flows begin in V2.2 and V2.3.

## Inputs

Each `UtilizationRegime` belongs to one lease or transition and has inclusive start and end dates.

| Pattern | Required inputs | Behavior |
|---|---|---|
| `fixed_monthly` | Monthly FH and FC | Applies the same monthly values, prorated for partial months |
| `seasonal_profile` | Monthly FH and FC plus 12 FH factors and 12 FC factors | Multiplies the base values by the factor for each calendar month |
| `explicit_months` | One dated FH/FC override for every covered calendar month | Uses only the stated monthly values and rejects missing months |

An override takes precedence over a fixed or seasonal value. A transition with no flying must have an explicit regime with zero FH and zero FC.

If a `KnownState` is supplied, its date and TTSN/TCSN are authoritative. The calculated timeline begins on the following day. Without a known state, modeled cumulative usage begins at zero on the first lifecycle day.

## Period construction

The engine creates a new row at every:

- calendar month-end;
- lifecycle segment boundary;
- utilization regime boundary;
- analysis-date boundary; and
- comparison horizon.

Monthly FH and FC are multiplied by inclusive slice days divided by calendar days in that month. No rounding is applied inside the technical timeline.

## Output

Each row identifies its segment, regime, pattern, actual/assumption status and input source. It records slice start/end dates, day-count proration, FH, FC, TTSN and TCSN. A known-state anchor is period zero and contains no incremental usage.

The stable column order is defined by `LIFECYCLE_UTILIZATION_COLUMNS` in `lifecycle_utilization.py`.

## Validation

The model rejects:

- overlapping lifecycle segments or utilization regimes;
- uncovered lifecycle days, including implicit downtime;
- regimes outside their owning segment;
- negative FH, FC or seasonal factors;
- seasonal profiles without exactly 12 FH and 12 FC factors;
- explicit-month regimes without an override for every covered month;
- duplicate override months; and
- actual utilization extending beyond the analysis date.
