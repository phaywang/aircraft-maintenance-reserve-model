"""Orchestrate deterministic evidence, Bedrock synthesis and report validation."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import re
from typing import Any, Callable

from ..scenario_builder import build_scenario_payload
from ..dashboard_service import case_from_payload, run_dashboard_case
from ..case_questions import calculate_next_engine_interval_sensitivity
from .analysis_packet import (
    build_comparison_analysis_packet,
    build_scenario_analysis_packet,
    build_v1_analysis_packet,
    build_v1_case_questions_packet,
)
from .bedrock_client import TextInvokeResult, invoke_text
from .guardrails import numeric_guardrail_check, strip_blocked_financial_lines
from .prompts import (
    SYSTEM_PROMPT,
    build_repair_prompt,
    build_report_prompt,
    build_v1_analysis_prompt,
    build_v2_question_prompt,
)


class ReportValidationError(RuntimeError):
    """Raised when generated prose fails deterministic publication checks."""


def _format_fh(value: object) -> str:
    amount = Decimal(str(value))
    return f"{amount:,.0f} FH"


def _v1_sensitivity_section(
    packet: dict[str, Any], heading: str = "## Question 3 — Engine Interval Sensitivity"
) -> str:
    """Render the mandatory quantitative Q3 section from verified evidence."""

    claim_map = {
        claim["claim_id"]: claim for claim in packet["verified_claims"]
    }
    adjustment_id = packet.get("interval_change_claim")
    if adjustment_id is None:
        adjustment_id = packet["questions"][2]["interval_change_claim"]
    adjustment = claim_map[adjustment_id]
    names = {
        "lower_5pct": "Lower interval",
        "base": "Base",
        "higher_5pct": "Higher interval",
    }
    rows = []
    for item in packet["engine_interval_sensitivity"]:
        name = names[item["case"]]
        if not item["event_in_forecast"]:
            rows.append(
                f"| {name} | {_format_fh(item['engine_interval_fh'])} | "
                f"{_format_fh(item['event_target_fh'])} | Outside forecast | — | — | — | — | — |"
            )
            continue
        values = {
            key: claim_map[claim_id]
            for key, claim_id in item["verified_claims"].items()
        }
        cell = lambda key: (
            f"{values[key]['display']} [verified: {values[key]['claim_id']}]"
        )
        rows.append(
            f"| {name} | {_format_fh(item['engine_interval_fh'])} | "
            f"{_format_fh(item['event_target_fh'])} | {item['event_date']} | "
            f"{cell('event_cost')} | {cell('available_reserve')} | "
            f"{cell('reimbursement')} | {cell('shortfall')} | "
            f"{cell('coverage_ratio')} |"
        )
    result = packet.get("sensitivity_result")
    if result is None:
        result = packet["questions"][2]["narrow_cashflow_result"]
    by_case = {item["case"]: item for item in packet["engine_interval_sensitivity"]}
    if result in {"lower_5pct", "higher_5pct"}:
        winner = names[result]
        loser_key = "higher_5pct" if result == "lower_5pct" else "lower_5pct"
        winner_claim = claim_map[by_case[result]["verified_claims"]["reimbursement"]]
        loser_claim = claim_map[by_case[loser_key]["verified_claims"]["reimbursement"]]
        conclusion = (
            f"Under the narrow lessor reimbursement-cash-outflow definition, the **{winner.lower()}** "
            f"is more advantageous: its modeled next-event reimbursement is "
            f"{winner_claim['display']} [verified: {winner_claim['claim_id']}], compared with "
            f"{loser_claim['display']} [verified: {loser_claim['claim_id']}] for the "
            f"{names[loser_key].lower()}. The lower-of rule caps reimbursement at the component "
            "reserve available at the event date."
        )
    elif result == "equal":
        conclusion = (
            "Under the narrow lessor reimbursement-cash-outflow definition, the lower and "
            "higher intervals produce the same next-event reimbursement."
        )
    else:
        conclusion = (
            "The lessor reimbursement comparison cannot be determined within the forecast "
            "because not all three next-event scenarios occur before lease expiry."
        )
    return "\n".join([
        heading,
        "",
        f"The deterministic sensitivity changes the next engine interval by "
        f"{adjustment['display']} [verified: {adjustment['claim_id']}] below and above the baseline, "
        "while holding the historical opening position constant.",
        "",
        "### Comparative Summary",
        "",
        "| Scenario | Interval (FH) | Target FH | Event Date | Event Cost | Reserve Available | Reimbursement | Shortfall | Coverage |",
        "|---|---:|---:|---|---:|---:|---:|---:|---:|",
        *rows,
        "",
        conclusion,
        "",
        "This conclusion does not assess aircraft value, technical-condition benefit, lessee "
        "credit risk or collectability.",
    ])


def _replace_v1_sensitivity_section(
    report_text: str, packet: dict[str, Any]
) -> str:
    section = _v1_sensitivity_section(packet)
    question_match = re.search(
        r"^## Question 3\s+[^\n]*", report_text, flags=re.MULTILINE
    )
    scope_match = re.search(
        r"^## Model Scope and Limitations\s*$", report_text, flags=re.MULTILINE
    )
    if question_match:
        prefix = report_text[:question_match.start()].rstrip()
        suffix = report_text[scope_match.start():].strip() if scope_match else ""
        combined = f"{prefix}\n\n{section}"
        if suffix:
            combined += f"\n\n{suffix}"
        else:
            combined += (
                "\n\n## Model Scope and Limitations\n\n"
                "The model covers maintenance reserve funding only; broader asset economics "
                "and counterparty recoverability are outside scope."
            )
        return combined
    return f"{report_text.rstrip()}\n\n{section}"


def _replace_v1_analysis_sensitivity_section(
    report_text: str, packet: dict[str, Any]
) -> str:
    """Replace or insert the general analysis sensitivity section."""

    section = _v1_sensitivity_section(packet, "## Engine Interval Sensitivity")
    section_match = re.search(
        r"^## Engine Interval Sensitivity\s*$", report_text, flags=re.MULTILINE
    )
    scope_match = re.search(
        r"^## Model Scope and Limitations\s*$", report_text, flags=re.MULTILINE
    )
    if section_match:
        suffix_start = scope_match.start() if scope_match else len(report_text)
        prefix = report_text[:section_match.start()].rstrip()
        suffix = report_text[suffix_start:].strip()
        return f"{prefix}\n\n{section}" + (f"\n\n{suffix}" if suffix else "")
    if scope_match:
        prefix = report_text[:scope_match.start()].rstrip()
        suffix = report_text[scope_match.start():].strip()
        return f"{prefix}\n\n{section}\n\n{suffix}"
    return f"{report_text.rstrip()}\n\n{section}"


def _normalize_analysis_wording(report_text: str) -> str:
    """Keep public analysis language neutral and product-oriented."""

    return re.sub(r"\bbase[- ]case\b", "baseline", report_text, flags=re.IGNORECASE)


def _validate_v1_response(
    prompt: str,
    response: TextInvokeResult,
    packet: dict[str, Any],
    *,
    invoke: Callable[..., TextInvokeResult],
    sensitivity_section: bool,
) -> tuple[TextInvokeResult, bool, int, dict[str, Any]]:
    """Apply optional deterministic sensitivity rendering and numeric checks."""

    if sensitivity_section:
        response = TextInvokeResult(
            text=_replace_v1_analysis_sensitivity_section(response.text, packet),
            stop_reason=response.stop_reason,
            model_id=response.model_id,
        )
    guardrail = numeric_guardrail_check(response.text, packet["verified_claims"])
    repaired = False
    removed_line_count = 0
    if guardrail["status"] != "pass":
        repaired = True
        blocked_lines = [
            item["line"] for item in guardrail["blocked_claims"]
        ] + [
            f"Unknown verified tag: {tag}"
            for tag in guardrail["unknown_verified_tags"]
        ]
        response = invoke(
            build_repair_prompt(prompt, response.text, blocked_lines),
            system_prompt=SYSTEM_PROMPT,
            max_tokens=3200,
        )
        if sensitivity_section:
            response = TextInvokeResult(
                text=_replace_v1_analysis_sensitivity_section(response.text, packet),
                stop_reason=response.stop_reason,
                model_id=response.model_id,
            )
        guardrail = numeric_guardrail_check(response.text, packet["verified_claims"])
    if guardrail["status"] != "pass":
        sanitized_text, removed_line_count = strip_blocked_financial_lines(
            response.text, guardrail
        )
        response = TextInvokeResult(
            text=sanitized_text,
            stop_reason=response.stop_reason,
            model_id=response.model_id,
        )
        guardrail = numeric_guardrail_check(response.text, packet["verified_claims"])
        if guardrail["status"] != "pass" or len(response.text) < 80:
            raise ReportValidationError(
                "Bedrock V1 analysis failed verified-number checks"
            )
    response = TextInvokeResult(
        text=_normalize_analysis_wording(response.text),
        stop_reason=response.stop_reason,
        model_id=response.model_id,
    )
    return response, repaired, removed_line_count, guardrail


def generate_v1_analysis(
    case_payload: dict[str, Any],
    *,
    mode: str,
    report_type: str | None = None,
    question: str | None = None,
    invoke: Callable[..., TextInvokeResult] = invoke_text,
) -> dict[str, Any]:
    """Generate a current-run report or answer a user-defined V1 question."""

    case = case_from_payload(case_payload)
    base_result = run_dashboard_case(case)
    sensitivity = calculate_next_engine_interval_sensitivity(case, base_result)
    packet = build_v1_analysis_packet(base_result, sensitivity)
    prompt = build_v1_analysis_prompt(
        packet, mode=mode, report_type=report_type, question=question
    )
    response = invoke(prompt, system_prompt=SYSTEM_PROMPT, max_tokens=3200)
    include_sensitivity = mode == "report" and report_type in {
        "full_analysis", "engine_interval_sensitivity"
    }
    response, repaired, removed_line_count, guardrail = _validate_v1_response(
        prompt, response, packet, invoke=invoke,
        sensitivity_section=include_sensitivity,
    )
    return {
        "mode": mode,
        "report_type": report_type if mode == "report" else None,
        "question": question.strip() if mode == "question" and question else None,
        "report_markdown": _normalize_analysis_wording(response.text),
        "model_id": response.model_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_input_signature": base_result["run"]["input_signature"],
        "guardrail_status": "repaired" if repaired else "pass",
        "verified_claim_count": len(packet["verified_claims"]),
        "financial_numbers_checked": guardrail["financial_numbers_checked"],
        "removed_line_count": removed_line_count,
        "stop_reason": response.stop_reason,
        "language": "en",
        "perspective": "lessor",
    }


def generate_analysis_report(
    report_type: str,
    scenario_inputs: list[dict[str, Any]],
    *,
    invoke: Callable[..., TextInvokeResult] = invoke_text,
) -> dict[str, Any]:
    if report_type not in {"current_scenario", "cross_scenario"}:
        raise ValueError("report_type must be current_scenario or cross_scenario")
    if not scenario_inputs:
        raise ValueError("at least one scenario is required")
    if report_type == "current_scenario" and len(scenario_inputs) != 1:
        raise ValueError("current_scenario reports require exactly one scenario")
    if report_type == "cross_scenario" and len(scenario_inputs) < 2:
        raise ValueError("cross_scenario reports require at least two scenarios")

    results = [build_scenario_payload(item) for item in scenario_inputs]
    scenario_ids = [result["scenario"]["scenario_id"] for result in results]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise ValueError("scenario identifiers must be unique")
    packet = (
        build_scenario_analysis_packet(results[0])
        if report_type == "current_scenario"
        else build_comparison_analysis_packet(results)
    )
    prompt = build_report_prompt(packet, report_type)
    response = invoke(prompt, system_prompt=SYSTEM_PROMPT, max_tokens=3200)
    guardrail = numeric_guardrail_check(response.text, packet["verified_claims"])
    repaired = False
    removed_line_count = 0
    if guardrail["status"] != "pass":
        repaired = True
        blocked_lines = [
            item["line"] for item in guardrail["blocked_claims"]
        ] + [f"Unknown verified tag: {tag}" for tag in guardrail["unknown_verified_tags"]]
        repair = invoke(
            build_repair_prompt(prompt, response.text, blocked_lines),
            system_prompt=SYSTEM_PROMPT,
            max_tokens=3200,
        )
        response = repair
        guardrail = numeric_guardrail_check(response.text, packet["verified_claims"])
    if guardrail["status"] != "pass":
        sanitized_text, removed_line_count = strip_blocked_financial_lines(
            response.text, guardrail
        )
        response = TextInvokeResult(
            text=sanitized_text,
            stop_reason=response.stop_reason,
            model_id=response.model_id,
        )
        guardrail = numeric_guardrail_check(response.text, packet["verified_claims"])
        if guardrail["status"] != "pass" or len(response.text) < 80:
            raise ReportValidationError(
                "Bedrock report failed verified-number checks after deterministic repair"
            )
    return {
        "report_type": report_type,
        "report_markdown": response.text,
        "model_id": response.model_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scenario_ids": scenario_ids,
        "guardrail_status": "repaired" if repaired else "pass",
        "verified_claim_count": len(packet["verified_claims"]),
        "financial_numbers_checked": guardrail["financial_numbers_checked"],
        "removed_line_count": removed_line_count,
        "stop_reason": response.stop_reason,
        "language": "en",
        "perspective": "lessor",
    }


def generate_analysis_answer(
    analysis_scope: str,
    scenario_inputs: list[dict[str, Any]],
    question: str,
    *,
    invoke: Callable[..., TextInvokeResult] = invoke_text,
) -> dict[str, Any]:
    """Answer a V2 lifecycle question from current or comparison evidence."""

    if analysis_scope not in {"current_scenario", "cross_scenario"}:
        raise ValueError(
            "analysis_scope must be current_scenario or cross_scenario"
        )
    if not scenario_inputs:
        raise ValueError("at least one scenario is required")
    if analysis_scope == "current_scenario" and len(scenario_inputs) != 1:
        raise ValueError("current_scenario questions require exactly one scenario")
    if analysis_scope == "cross_scenario" and len(scenario_inputs) < 2:
        raise ValueError("cross_scenario questions require at least two scenarios")
    results = [build_scenario_payload(item) for item in scenario_inputs]
    scenario_ids = [result["scenario"]["scenario_id"] for result in results]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise ValueError("scenario identifiers must be unique")
    packet = (
        build_scenario_analysis_packet(results[0])
        if analysis_scope == "current_scenario"
        else build_comparison_analysis_packet(results)
    )
    prompt = build_v2_question_prompt(
        packet, question=question, analysis_scope=analysis_scope
    )
    response = invoke(prompt, system_prompt=SYSTEM_PROMPT, max_tokens=3200)
    guardrail = numeric_guardrail_check(response.text, packet["verified_claims"])
    repaired = False
    removed_line_count = 0
    if guardrail["status"] != "pass":
        repaired = True
        blocked_lines = [
            item["line"] for item in guardrail["blocked_claims"]
        ] + [
            f"Unknown verified tag: {tag}"
            for tag in guardrail["unknown_verified_tags"]
        ]
        response = invoke(
            build_repair_prompt(prompt, response.text, blocked_lines),
            system_prompt=SYSTEM_PROMPT,
            max_tokens=3200,
        )
        guardrail = numeric_guardrail_check(
            response.text, packet["verified_claims"]
        )
    if guardrail["status"] != "pass":
        sanitized_text, removed_line_count = strip_blocked_financial_lines(
            response.text, guardrail
        )
        response = TextInvokeResult(
            text=sanitized_text,
            stop_reason=response.stop_reason,
            model_id=response.model_id,
        )
        guardrail = numeric_guardrail_check(
            response.text, packet["verified_claims"]
        )
        if guardrail["status"] != "pass" or len(response.text) < 80:
            raise ReportValidationError(
                "Bedrock V2 answer failed verified-number checks"
            )
    return {
        "mode": "question",
        "analysis_scope": analysis_scope,
        "question": question.strip(),
        "report_markdown": response.text,
        "model_id": response.model_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scenario_ids": scenario_ids,
        "guardrail_status": "repaired" if repaired else "pass",
        "verified_claim_count": len(packet["verified_claims"]),
        "financial_numbers_checked": guardrail["financial_numbers_checked"],
        "removed_line_count": removed_line_count,
        "stop_reason": response.stop_reason,
        "language": "en",
        "perspective": "lessor",
    }


def generate_v1_case_questions_report(
    case_payload: dict[str, Any],
    *,
    invoke: Callable[..., TextInvokeResult] = invoke_text,
) -> dict[str, Any]:
    """Prepare the V1 maintenance-reserve analysis from deterministic evidence."""

    case = case_from_payload(case_payload)
    base_result = run_dashboard_case(case)
    sensitivity = calculate_next_engine_interval_sensitivity(case, base_result)
    packet = build_v1_case_questions_packet(base_result, sensitivity)
    prompt = build_report_prompt(packet, "v1_case_questions")
    response = invoke(prompt, system_prompt=SYSTEM_PROMPT, max_tokens=3200)
    response = TextInvokeResult(
        text=_replace_v1_sensitivity_section(response.text, packet),
        stop_reason=response.stop_reason,
        model_id=response.model_id,
    )
    guardrail = numeric_guardrail_check(response.text, packet["verified_claims"])
    repaired = False
    removed_line_count = 0
    if guardrail["status"] != "pass":
        repaired = True
        blocked_lines = [
            item["line"] for item in guardrail["blocked_claims"]
        ] + [f"Unknown verified tag: {tag}" for tag in guardrail["unknown_verified_tags"]]
        response = invoke(
            build_repair_prompt(prompt, response.text, blocked_lines),
            system_prompt=SYSTEM_PROMPT,
            max_tokens=3200,
        )
        response = TextInvokeResult(
            text=_replace_v1_sensitivity_section(response.text, packet),
            stop_reason=response.stop_reason,
            model_id=response.model_id,
        )
        guardrail = numeric_guardrail_check(response.text, packet["verified_claims"])
    if guardrail["status"] != "pass":
        sanitized_text, removed_line_count = strip_blocked_financial_lines(
            response.text, guardrail
        )
        response = TextInvokeResult(
            text=sanitized_text,
            stop_reason=response.stop_reason,
            model_id=response.model_id,
        )
        guardrail = numeric_guardrail_check(response.text, packet["verified_claims"])
        if guardrail["status"] != "pass" or len(response.text) < 80:
            raise ReportValidationError(
                "Bedrock V1 analysis failed verified-number checks"
            )
    return {
        "report_type": "v1_case_questions",
        "report_markdown": response.text,
        "model_id": response.model_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_input_signature": base_result["run"]["input_signature"],
        "guardrail_status": "repaired" if repaired else "pass",
        "verified_claim_count": len(packet["verified_claims"]),
        "financial_numbers_checked": guardrail["financial_numbers_checked"],
        "removed_line_count": removed_line_count,
        "stop_reason": response.stop_reason,
        "language": "en",
        "perspective": "lessor",
    }
