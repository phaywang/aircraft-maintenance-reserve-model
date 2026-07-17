"""Deterministic numeric and citation checks for LLM-written reports."""

from __future__ import annotations

import re
from typing import Any, Iterable


FINANCIAL_NUMBER_RE = re.compile(
    r"(?:\$\s?[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?:\s*(?:billion|million|thousand|[bmk]))?)"
    r"|(?:[-+]?\d+(?:\.\d+)?%)",
    re.IGNORECASE,
)
VERIFIED_TAG_RE = re.compile(r"\[verified:\s*([A-Za-z0-9_:\-.]+)\]")


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def numeric_guardrail_check(
    report_text: str, verified_claims: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    claim_map = {
        str(claim["claim_id"]): _normalized(str(claim["display"]))
        for claim in verified_claims
        if claim.get("status") == "verified" and claim.get("claim_id")
    }
    blocked = []
    checked = []
    for line_number, line in enumerate(report_text.splitlines(), start=1):
        numbers = FINANCIAL_NUMBER_RE.findall(line)
        if not numbers:
            continue
        tags = VERIFIED_TAG_RE.findall(line)
        allowed_displays = {claim_map[tag] for tag in tags if tag in claim_map}
        for number in numbers:
            exact_match = _normalized(number) in allowed_displays
            item = {
                "line_number": line_number,
                "number": number,
                "line": line.strip(),
                "verified_tags": tags,
                "exact_verified_value": exact_match,
            }
            checked.append(item)
            if not exact_match:
                blocked.append(item)
    unknown_tags = sorted({
        tag for tag in VERIFIED_TAG_RE.findall(report_text) if tag not in claim_map
    })
    return {
        "status": "block" if blocked or unknown_tags else "pass",
        "financial_numbers_checked": len(checked),
        "blocked_count": len(blocked),
        "blocked_claims": blocked,
        "unknown_verified_tags": unknown_tags,
    }


def strip_blocked_financial_lines(
    report_text: str, report: dict[str, Any]
) -> tuple[str, int]:
    """Remove lines that cannot be deterministically bound to verified values."""

    blocked_numbers = {item["line_number"] for item in report["blocked_claims"]}
    unknown_tags = set(report["unknown_verified_tags"])
    kept = []
    removed = 0
    for line_number, line in enumerate(report_text.splitlines(), start=1):
        has_unknown_tag = bool(unknown_tags & set(VERIFIED_TAG_RE.findall(line)))
        if line_number in blocked_numbers or has_unknown_tag:
            removed += 1
            continue
        kept.append(line)
    if removed:
        kept.extend([
            "",
            "_Verification note: unsupported financial statements were removed "
            "before publication._",
        ])
    return "\n".join(kept).strip(), removed
