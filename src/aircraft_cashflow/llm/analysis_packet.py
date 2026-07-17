"""Build compact, verified evidence packets for English LLM analysis."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Iterable


SUMMARY_METRICS = {
    "total_reserve_collections": ("Total maintenance reserve collected", "currency"),
    "total_event_cost": ("Total maintenance event cost", "currency"),
    "total_reserve_reimbursement": ("Total reserve reimbursement", "currency"),
    "total_lessee_unfunded": ("Total modeled lessee top-up", "currency"),
    "largest_lessee_top_up": ("Largest single modeled lessee top-up", "currency"),
    "reserve_funding_coverage": ("Reserve funding coverage", "percent"),
    "retained_reserve": ("Reserve retained by lessor", "currency"),
    "total_reserve_refunds": ("Reserve refunded to lessee", "currency"),
    "net_reserve_cash_movement": ("Net maintenance reserve cash movement", "currency"),
}


def _safe(value: object) -> str:
    return "".join(char if char.isalnum() or char in "_.-" else "-" for char in str(value))


def _decimal(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def _display(value: Decimal, unit: str) -> str:
    if unit == "percent":
        return f"{value * Decimal('100'):.1f}%"
    if value < 0:
        return f"-${abs(value):,.2f}"
    return f"${value:,.2f}"


def _claim(
    claim_id: str, label: str, value: object, unit: str, context: str,
) -> dict[str, str]:
    decimal_value = _decimal(value)
    return {
        "claim_id": claim_id,
        "status": "verified",
        "label": label,
        "value": str(decimal_value),
        "unit": unit,
        "display": _display(decimal_value, unit),
        "context": context,
    }


def build_scenario_analysis_packet(result: dict[str, Any]) -> dict[str, Any]:
    """Convert one deterministic scenario result into report-ready evidence."""

    scenario = result["scenario"]
    scenario_id = _safe(scenario["scenario_id"])
    context = f"Scenario {scenario['name']}"
    claims: list[dict[str, str]] = []
    for key, (label, unit) in SUMMARY_METRICS.items():
        claims.append(_claim(
            f"scenario:{scenario_id}:summary:{key}", label,
            result["summary"][key], unit, context,
        ))

    event_evidence = []
    component_totals: dict[str, dict[str, Decimal | int]] = defaultdict(
        lambda: {"event_cost": Decimal("0"), "reimbursement": Decimal("0"),
                 "top_up": Decimal("0"), "events": 0}
    )
    for event in result["events"]:
        event_id = _safe(event["event_id"])
        component = str(event["component_code"])
        prefix = f"scenario:{scenario_id}:event:{event_id}"
        event_claims = {}
        for key, label in (
            ("event_cost", "Escalated maintenance event cost"),
            ("available_reserve", "Component reserve available at event"),
            ("reserve_reimbursement", "Reserve reimbursement at event"),
            ("lessee_unfunded_amount", "Modeled lessee top-up at event"),
        ):
            claim = _claim(
                f"{prefix}:{key}", label, event[key], "currency",
                f"{component} event {event_id} on {event['date']}",
            )
            claims.append(claim)
            event_claims[key] = claim["claim_id"]
        totals = component_totals[component]
        totals["event_cost"] += _decimal(event["event_cost"])
        totals["reimbursement"] += _decimal(event["reserve_reimbursement"])
        totals["top_up"] += _decimal(event["lessee_unfunded_amount"])
        totals["events"] += 1
        event_evidence.append({
            "event_id": event["event_id"],
            "component": component,
            "component_name": event["component_name"],
            "date": event["date"],
            "lease_id": event["lease_id"],
            "verified_claims": event_claims,
        })

    component_evidence = []
    for component, totals in sorted(component_totals.items()):
        prefix = f"scenario:{scenario_id}:component:{_safe(component)}"
        component_claims = {}
        for key, label in (
            ("event_cost", "Aggregate component event cost"),
            ("reimbursement", "Aggregate component reserve reimbursement"),
            ("top_up", "Aggregate component lessee top-up"),
        ):
            claim = _claim(
                f"{prefix}:{key}", label, totals[key], "currency",
                f"{component} events across {scenario['name']}",
            )
            claims.append(claim)
            component_claims[key] = claim["claim_id"]
        component_evidence.append({
            "component": component,
            "event_count": totals["events"],
            "verified_claims": component_claims,
        })

    leases = []
    for lease in scenario["leases"]:
        lease_id = _safe(lease["contract_id"])
        accounts = []
        for account in lease["reserve_accounts"]:
            component = _safe(account["component_code"])
            rate_claim = _claim(
                f"scenario:{scenario_id}:lease:{lease_id}:rate:{component}",
                "Contract maintenance reserve base rate", account["base_rate"],
                "currency", f"{lease['contract_id']} {component} reserve term",
            )
            escalation_claim = _claim(
                f"scenario:{scenario_id}:lease:{lease_id}:escalation:{component}",
                "Contract maintenance reserve annual escalation",
                account["annual_escalation"], "percent",
                f"{lease['contract_id']} {component} reserve term",
            )
            claims.extend([rate_claim, escalation_claim])
            accounts.append({
                "component": account["component_code"],
                "reserve_basis": account["reserve_basis"],
                "rate_base_date": account["rate_base_date"],
                "closeout_rule": account["closeout_rule"],
                "verified_claims": {
                    "base_rate": rate_claim["claim_id"],
                    "annual_escalation": escalation_claim["claim_id"],
                },
            })
        leases.append({
            "lease_id": lease["contract_id"],
            "lessee": lease["lessee"],
            "start_date": lease["start_date"],
            "end_date": lease["end_date"],
            "reserve_accounts": accounts,
        })

    maintenance_program = []
    for component in scenario["asset"]["components"]:
        code = _safe(component["code"])
        cost_claim = _claim(
            f"scenario:{scenario_id}:maintenance:{code}:base_cost",
            "Base maintenance event cost", component["base_cost"], "currency",
            f"{component['code']} aircraft maintenance program assumption",
        )
        escalation_claim = _claim(
            f"scenario:{scenario_id}:maintenance:{code}:cost_escalation",
            "Annual maintenance-cost escalation",
            component["annual_cost_escalation"], "percent",
            f"{component['code']} aircraft maintenance program assumption",
        )
        claims.extend([cost_claim, escalation_claim])
        maintenance_program.append({
            "component": component["code"],
            "component_name": component["name"],
            "event_driver": component["event_driver"],
            "event_interval": component["interval"],
            "cost_base_date": component["cost_base_date"],
            "verified_claims": {
                "base_cost": cost_claim["claim_id"],
                "annual_cost_escalation": escalation_claim["claim_id"],
            },
        })
    return {
        "report_scope": "current_scenario",
        "perspective": "lessor",
        "currency": scenario["currency"],
        "scenario": {
            "scenario_id": scenario["scenario_id"],
            "name": scenario["name"],
            "analysis_date": scenario["analysis_date"],
            "forecast_end": result["summary"]["forecast_end"],
            "forecast_months": result["summary"]["forecast_months"],
            "maintenance_event_count": result["summary"]["maintenance_event_count"],
            "opening_state_basis": result["resolved_known_state"]["basis"],
            "leases": leases,
            "utilization_regimes": scenario["utilization_regimes"],
        },
        "events": event_evidence,
        "components": component_evidence,
        "maintenance_program": maintenance_program,
        "verified_claims": claims,
        "model_scope": [
            "maintenance reserve collections",
            "maintenance event costs",
            "component-account reimbursements",
            "modeled lessee top-up obligations",
            "reserve close-out treatment",
        ],
        "excluded_scope": [
            "base rent",
            "aircraft market value",
            "time value of money",
            "credit risk and recoverability of lessee obligations",
            "downtime and transition costs",
        ],
    }


def build_comparison_analysis_packet(
    results: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    packets = [build_scenario_analysis_packet(result) for result in results]
    return {
        "report_scope": "cross_scenario",
        "perspective": "lessor",
        "scenario_count": len(packets),
        "scenarios": [packet["scenario"] for packet in packets],
        "component_evidence": [
            {"scenario_id": packet["scenario"]["scenario_id"],
             "components": packet["components"]}
            for packet in packets
        ],
        "verified_claims": [
            claim for packet in packets for claim in packet["verified_claims"]
        ],
        "comparison_rule": (
            "Explain absolute outcomes and trade-offs. Do not rank a best scenario "
            "without a user-supplied decision objective."
        ),
        "excluded_scope": packets[0]["excluded_scope"] if packets else [],
    }


def build_v1_case_questions_packet(
    base_result: dict[str, Any],
    sensitivity_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build verified evidence for the V1 maintenance-reserve analysis."""

    claims: list[dict[str, str]] = []
    case = base_result["case"]
    lessee = case["lessee"]
    lessee_possessive = f"{lessee}'" if str(lessee).lower().endswith("s") else f"{lessee}'s"
    total_claim = _claim(
        "v1:summary:total_unfunded", "Total maintenance expenditure not funded by MR",
        base_result["summary"]["forecast_shortfall"], "currency",
        "Aggregate forecast shortfall across all component events",
    )
    claims.append(total_claim)
    interval_change_claim = _claim(
        "v1:sensitivity:interval_change", "Engine interval sensitivity adjustment",
        Decimal("0.05"), "percent",
        "Adjustment applied below and above the base next-engine interval",
    )
    claims.append(interval_change_claim)

    component_evidence = []
    for event in base_result["funding_events"]:
        code = _safe(event["component"])
        prefix = f"v1:event:{code}:{_safe(event['event_date'])}"
        event_claims = {}
        for key, label, unit in (
            ("event_cost", "Escalated event cost", "currency"),
            ("available_reserve", "Component reserve available", "currency"),
            ("reimbursement", "MR reimbursement", "currency"),
            ("shortfall", "Unfunded maintenance expenditure", "currency"),
            ("coverage_ratio", "MR coverage ratio", "percent"),
        ):
            claim = _claim(
                f"{prefix}:{key}", label, event[key], unit,
                f"{event['component']} event on {event['event_date']}",
            )
            claims.append(claim)
            event_claims[key] = claim["claim_id"]
        component_evidence.append({
            "component": event["component"],
            "component_name": event["component_name"],
            "event_date": event["event_date"],
            "fully_funded": event["fully_funded"],
            "verified_claims": event_claims,
        })

    def engine_case_evidence(item: dict[str, Any]) -> dict[str, Any]:
        label = str(item["case"])
        evidence: dict[str, Any] = {
            "case": label,
            "engine_interval_fh": item["engine_interval_fh"],
            "event_target_fh": item["event_target_fh"],
            "event_in_forecast": item["event_in_forecast"],
        }
        if not item["event_in_forecast"]:
            return evidence
        prefix = f"v1:sensitivity:{label}"
        sensitivity_claims = {}
        for key, claim_label in (
            ("event_cost", "Next E1 event cost"),
            ("available_reserve", "E1 reserve available at event"),
            ("reimbursement", "E1 reimbursement at event"),
            ("shortfall", "E1 shortfall at event"),
            ("coverage_ratio", "E1 coverage ratio at event"),
        ):
            unit = "percent" if key == "coverage_ratio" else "currency"
            claim = _claim(
                f"{prefix}:{key}", claim_label, item[key], unit,
                f"{label} engine-interval case; E1 event on {item['event_date']}",
            )
            claims.append(claim)
            sensitivity_claims[key] = claim["claim_id"]
        evidence.update({
            "event_date": item["event_date"],
            "verified_claims": sensitivity_claims,
        })
        return evidence

    sensitivity = [engine_case_evidence(item) for item in sensitivity_cases]
    available = [item for item in sensitivity if item["event_in_forecast"]]
    if len(available) == 3:
        reimbursement_by_case = {
            item["case"]: _decimal(item["reimbursement"])
            for item in sensitivity_cases
        }
        lower_reimbursement = reimbursement_by_case["lower_5pct"]
        higher_reimbursement = reimbursement_by_case["higher_5pct"]
        advantage = (
            "lower_5pct" if lower_reimbursement < higher_reimbursement
            else "higher_5pct" if higher_reimbursement < lower_reimbursement
            else "equal"
        )
    else:
        advantage = "not_determinable_within_forecast"

    return {
        "report_scope": "v1_original_case_questions",
        "perspective": "lessor",
        "case": {
            "aircraft_type": case["aircraft_type"],
            "lessee": lessee,
            "analysis_date": case["analysis_date"],
            "lease_expiry_date": case["lease_expiry_date"],
        },
        "questions": [
            {
                "question_number": 1,
                "text": f"How much of {lessee_possessive} maintenance expenditures will not be funded via Maintenance Reserve reimbursements?",
                "total_unfunded_claim": total_claim["claim_id"],
            },
            {
                "question_number": 2,
                "text": "Do the Maintenance Reserve rates for each component appear fair or unfair to the lessor and/or lessee, and why?",
                "assessment_basis": "event-level reserve coverage and shortfall by segregated component account",
            },
            {
                "question_number": 3,
                "text": "Is a 5% lower or 5% higher next engine shop-visit interval more advantageous to the lessor, and why?",
                "interval_change_claim": interval_change_claim["claim_id"],
                "narrow_cashflow_result": advantage,
            },
        ],
        "component_event_evidence": component_evidence,
        "engine_interval_sensitivity": sensitivity,
        "verified_claims": claims,
        "interpretation_rules": [
            "A coverage ratio below 100% means the modeled reimbursement is constrained by the component reserve available.",
            "A coverage ratio above 100% does not by itself establish economic unfairness; treatment of surplus reserve depends on the lease terms.",
            "For Question 3, 'advantageous to the lessor' is limited to lower modeled MR reimbursement cash outflow for the next engine event.",
            "Do not infer aircraft value, technical-condition benefit, lessee credit risk or collectability because those items are outside the model.",
        ],
    }


def build_v1_analysis_packet(
    base_result: dict[str, Any],
    sensitivity_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a general current-run evidence packet for V1 analysis and Q&A."""

    packet = build_v1_case_questions_packet(base_result, sensitivity_cases)
    interval_change_claim = packet["questions"][2]["interval_change_claim"]
    sensitivity_result = packet["questions"][2]["narrow_cashflow_result"]
    assumption_evidence = []
    for component in base_result["case"]["components"]:
        code = _safe(component["code"])
        context = f"{component['code']} configured model assumption"
        assumption_claims = {}
        for key, label, unit in (
            ("base_reserve_rate", "Base maintenance reserve rate", "currency"),
            ("annual_reserve_escalation", "Annual reserve-rate escalation", "percent"),
            ("base_cost", "Base maintenance event cost", "currency"),
            ("annual_cost_escalation", "Annual maintenance-cost escalation", "percent"),
        ):
            claim = _claim(
                f"v1:assumption:{code}:{key}", label, component[key], unit, context,
            )
            packet["verified_claims"].append(claim)
            assumption_claims[key] = claim["claim_id"]
        assumption_evidence.append({
            "component": component["code"],
            "component_name": component["name"],
            "event_driver": component["event_driver"],
            "event_interval": component["interval"],
            "reserve_basis": component["reserve_basis"],
            "verified_claims": assumption_claims,
        })
    packet.update({
        "report_scope": "v1_current_run_analysis",
        "analysis_capabilities": [
            "forecast maintenance funding adequacy",
            "component reserve-rate alignment",
            "event-level shortfall and coverage",
            "next-engine interval sensitivity",
            "lease-expiry reserve position",
        ],
        "interval_change_claim": interval_change_claim,
        "sensitivity_result": sensitivity_result,
        "component_assumptions": assumption_evidence,
        "question_handling_rule": (
            "Answer only from this calculated run. If a question requires a new "
            "assumption or recalculation, direct the user to edit inputs and rerun "
            "the deterministic model."
        ),
    })
    packet.pop("questions", None)
    return packet
