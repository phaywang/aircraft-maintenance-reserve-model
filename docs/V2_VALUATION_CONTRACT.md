# V2.5 Common-Horizon Valuation Contract

V2.5 compares complete lifecycle alternatives using dated cash flows, one valuation date and one common economic horizon.

## Required comparison basis

Every alternative must share the same physical asset, currency and valuation date. Each scenario must explicitly extend through the chosen common horizon and provide a terminal value on that date. A shorter lease can be compared only after its post-lease transition, sale or continuation period is modeled through the horizon.

## Cash flows

Operating cash flow includes rent, maintenance reserves, maintenance cost, redelivery compensation, reserve refunds and transition costs. Terminal value equals stated aircraft value less selling cost. Cash flows before the valuation date are excluded.

## Discounting

Each cash flow is discounted by its exact number of days from the valuation date using the supplied annual rate and a 365-day exponent. The detailed table preserves nominal amount, days, discount factor and present value.

## Outputs

The summary reports operating cash flow, terminal value, NPV, incremental NPV versus the selected baseline, and major economic drivers. An alternative is not ranked using partial cash flows or an unmatched horizon.
