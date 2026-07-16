"""V2.7 deterministic conclusions and optional LLM explanation contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal

from .transitions import AlternativeSet, build_lifecycle_economics
from .valuation import ValuationResult


@dataclass(frozen=True)
class AlternativeDiagnostic:
    alternative_id: str
    rank: int
    npv: Decimal
    incremental_npv: Decimal
    maintenance_event_count: int
    total_unfunded_exposure: Decimal
    net_redelivery_cash: Decimal
    minimum_period_cashflow: Decimal
    terminal_value_pv_share: Decimal


@dataclass(frozen=True)
class DecisionAnalysis:
    recommended_alternative_id: str
    recommendation_basis: str
    npv_lead: Decimal
    npv_lead_ratio: Decimal
    decision_signal: str
    key_findings: tuple[str, ...]
    alternatives: tuple[AlternativeDiagnostic, ...]
    calculation_engine: str = "deterministic"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_decision_analysis(
    alternatives: AlternativeSet, valuation: ValuationResult
) -> DecisionAnalysis:
    """Generate repeatable conclusions using model results only."""

    summary = {
        row.alternative_id: row
        for row in valuation.summary.itertuples(index=False)
    }
    ranked = sorted(
        alternatives.alternatives,
        key=lambda item: Decimal(str(summary[item.alternative_id].npv)),
        reverse=True,
    )
    diagnostics: list[AlternativeDiagnostic] = []
    for rank, alternative in enumerate(ranked, start=1):
        economics = build_lifecycle_economics(alternative.scenario)
        events = economics.settlement.events
        cashflows = economics.cashflows
        npv = Decimal(str(summary[alternative.alternative_id].npv))
        terminal_pv = sum(
            (
                Decimal(str(row.present_value))
                for row in valuation.discounted_cashflows.itertuples(index=False)
                if row.alternative_id == alternative.alternative_id
                and row.cashflow_type == "terminal_value"
            ),
            Decimal("0"),
        )
        diagnostics.append(
            AlternativeDiagnostic(
                alternative.alternative_id,
                rank,
                npv,
                Decimal(str(summary[alternative.alternative_id].incremental_npv)),
                len(events),
                sum(events["unfunded_amount"], Decimal("0")),
                sum(
                    economics.settlement.redelivery["net_cash_compensation"],
                    Decimal("0"),
                ),
                min(cashflows["net_owner_cashflow"], default=Decimal("0")),
                terminal_pv / abs(npv) if npv else Decimal("0"),
            )
        )
    best, second = diagnostics[0], diagnostics[1]
    lead = best.npv - second.npv
    lead_ratio = lead / abs(second.npv) if second.npv else Decimal("0")
    signal = "clear_npv_lead" if lead_ratio >= Decimal("0.05") else "close_call"
    findings = (
        f"{best.alternative_id} has the highest modeled NPV by {lead}.",
        f"Its modeled unfunded maintenance exposure is {best.total_unfunded_exposure}.",
        f"Terminal value present value represents {best.terminal_value_pv_share} of its NPV.",
        f"The comparison signal is {signal}; assumptions should be tested in sensitivity analysis.",
    )
    return DecisionAnalysis(
        best.alternative_id,
        "highest_common_horizon_npv",
        lead,
        lead_ratio,
        signal,
        findings,
        tuple(diagnostics),
    )


def build_llm_explanation_payload(
    alternatives: AlternativeSet,
    valuation: ValuationResult,
    analysis: DecisionAnalysis,
    query: str = "Explain the recommendation, value drivers and material risks.",
) -> dict[str, object]:
    """Return facts for an optional language layer without invoking any LLM."""

    if not query.strip():
        raise ValueError("LLM explanation query must not be blank")
    return {
        "schema_version": "1.0",
        "task": "explain_deterministic_aircraft_lifecycle_results",
        "query": query,
        "guardrails": {
            "calculations_are_authoritative": True,
            "may_change_numbers": False,
            "may_change_ranking": False,
            "may_invent_market_data": False,
            "must_distinguish_fact_from_interpretation": True,
        },
        "comparison": {
            "comparison_id": alternatives.comparison_id,
            "baseline_id": valuation.baseline_id,
            "annual_discount_rate": valuation.annual_discount_rate,
            "common_horizon": valuation.common_horizon,
        },
        "deterministic_analysis": analysis.to_dict(),
        "valuation_facts": valuation.summary.to_dict("records"),
        "source_tables": [
            "valuation_summary",
            "discounted_cashflows",
            "maintenance_events",
            "redelivery_settlement",
            "reserve_ledger",
            "lifecycle_cashflows",
        ],
    }
