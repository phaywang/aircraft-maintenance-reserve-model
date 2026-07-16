# V2.7 Conclusions and LLM Explanation Contract

V2.7 separates decision logic from narrative generation.

## Deterministic conclusion

The recommended alternative is the highest common-horizon NPV. The engine reports the absolute and relative lead, a clear-lead or close-call signal, and diagnostics for maintenance events, unfunded exposure, redelivery cash, minimum period cash flow and terminal-value dependence.

These outputs are produced without an LLM and remain the authoritative conclusion.

## Optional LLM layer

`build_llm_explanation_payload()` prepares calculated facts, source-table names, deterministic conclusions and the user's requested analysis. It does not call an external model.

Any consuming LLM:

- may explain and organize calculated results;
- must distinguish fact from interpretation;
- may not alter numbers or ranking;
- may not invent market data; and
- must treat the deterministic calculation as authoritative.

Changing the narrative query cannot change model results or the recommendation.
