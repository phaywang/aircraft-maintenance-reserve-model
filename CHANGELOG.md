# Changelog

## 2.0.0a0 — in development

- Added the V2 lifecycle schema for aircraft, leases, transitions, utilization regimes, known state and terminal value.
- Added explicit expiry cut-off semantics and arbitrary-date stub periods.
- Added V1 migration adapters with exact Phase 1 calculation regression.
- Added a continuous variable-utilization timeline with fixed, seasonal and explicit-month inputs, actual-day stub proration and explicit zero-flight transitions.
- Added lease-specific rent and maintenance-reserve accounts with arbitrary-date periods, contract-specific escalation and expiry-period collection.

## 1.0.1 — in development

- Recalibrated synthetic reserve rates to produce funded, near-threshold and underfunded forecast events.
- Refreshed the deterministic regression baseline and embedded dashboard payloads.
- Added a reusable baseline-generation script and mixed-outcome regression test.

## 1.0.0 — 2026-07-15

- Added editable aircraft, maintenance-program, lease-term and utilization assumptions.
- Added monthly utilization, maintenance-event and reserve-inflow schedules.
- Added historical opening-balance reconstruction and component-level settlement.
- Added reserve adequacy, funding exceptions and model validation views.
- Added deterministic runtime checks and a versioned demonstration regression snapshot.
