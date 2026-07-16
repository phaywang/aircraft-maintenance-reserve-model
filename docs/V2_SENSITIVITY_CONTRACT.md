# V2.8 Sensitivity Contract

V2.8 measures how assumption changes affect alternative NPV and recommendation robustness without replacing the deterministic base case.

## Default drivers

- annual discount rate;
- monthly rent for each follow-on alternative;
- utilization for each alternative;
- aircraft maintenance cost for each alternative;
- transition costs; and
- terminal value.

Each low or high case creates immutable shocked scenarios and reruns utilization, events, reserve settlement, redelivery, transition economics and valuation. Results are not approximated by applying a percentage directly to base NPV.

## Nonlinearity

Utilization and maintenance assumptions may move an event across a lease boundary or common horizon. A sensitivity case can therefore create a discontinuous NPV change and recommendation switch. This behavior is reported, not smoothed away.

## Outputs

The case table reports the shock, target, winning alternative, winner and runner-up NPVs, NPV gap and recommendation-change flag. The driver summary reports minimum and maximum observed gap and the number of recommendation switches.

The uncertainty summary reports each alternative's observed minimum and maximum NPV, downside and upside from base, and recommendation frequency across the deterministic cases. These are scenario ranges, not probability-weighted forecasts.

The base-case recommendation remains authoritative for the stated base assumptions; sensitivity describes robustness and break risk.
