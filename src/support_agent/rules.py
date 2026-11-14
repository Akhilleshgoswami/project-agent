"""Deterministic escalation policy layered on top of model judgment."""

from __future__ import annotations

import re

from support_agent.schema import (
    SuggestedAction,
    TicketAnalysis,
    TicketCategory,
    TicketInput,
)

# Patterns that must never be auto-replied without a human.
SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    (r"\brefund\b", "refund / money movement"),
    (r"\bcharged\s+twice\b|\bduplicate\s+charge\b", "billing dispute"),
    (r"\bphish|\bseed\s+phrase\b|\bwallet\b", "security / phishing"),
    (r"\blegal\b|\battorney\b|\bgdpr\b|\bccpa\b", "legal / compliance"),
    (r"\bpassword\s+reset\b.*\blocked\b|\baccount\s+locked\b", "account lock / access"),
    (r"\btransfer\s+ownership\b|\bowner\s+email\b", "account ownership"),
    (r"\bcancel\s+(my\s+)?(subscription|account)\b", "subscription cancellation"),
]


def _combined_text(ticket: TicketInput) -> str:
    return f"{ticket.subject}\n{ticket.message}".lower()


def find_sensitive_match(ticket: TicketInput) -> str | None:
    text = _combined_text(ticket)
    for pattern, label in SENSITIVE_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return label
    return None


def apply_escalation_policy(
    ticket: TicketInput,
    analysis: TicketAnalysis,
    confidence_threshold: float,
) -> TicketAnalysis:
    """Force human_review when policy says so; clear reply_draft on escalate."""

    reasons: list[str] = []

    if analysis.confidence < confidence_threshold:
        reasons.append(
            f"confidence {analysis.confidence:.2f} below threshold {confidence_threshold:.2f}"
        )

    sensitive = find_sensitive_match(ticket)
    if sensitive:
        reasons.append(f"sensitive topic: {sensitive}")

    if analysis.category == TicketCategory.OTHER and analysis.suggested_action == SuggestedAction.DRAFT_REPLY:
        # Praise-only drafts are allowed; ambiguous "other" is not.
        text = _combined_text(ticket)
        praise = bool(re.search(r"\bthank|great|excellent|love|no action needed\b", text))
        if not praise:
            reasons.append("category other without clear safe reply")

    # Billing how-tos can draft; disputes/changes need a human.
    if (
        analysis.category == TicketCategory.BILLING
        and analysis.suggested_action == SuggestedAction.DRAFT_REPLY
        and (
            sensitive
            or re.search(r"\brefund|charge|invoice|cancel\b", _combined_text(ticket))
        )
    ):
        reasons.append("billing change or dispute needs human")

    if analysis.suggested_action == SuggestedAction.HUMAN_REVIEW:
        # Model already escalated; keep and enrich reason if policy adds more.
        if reasons and analysis.human_review_reason:
            analysis.human_review_reason = (
                f"{analysis.human_review_reason} | policy: {'; '.join(reasons)}"
            )
        elif reasons:
            analysis.human_review_reason = "; ".join(reasons)
            analysis.action_reason = f"Escalated by policy: {analysis.human_review_reason}"
        return analysis

    if reasons:
        analysis.suggested_action = SuggestedAction.HUMAN_REVIEW
        analysis.human_review_reason = "; ".join(reasons)
        analysis.action_reason = f"Escalated by policy: {analysis.human_review_reason}"
        analysis.reply_draft = None
        return analysis

    # Safe draft path: ensure we only keep drafts for questions (or praise other).
    if analysis.suggested_action == SuggestedAction.DRAFT_REPLY:
        if analysis.category not in (TicketCategory.QUESTION, TicketCategory.OTHER):
            analysis.suggested_action = SuggestedAction.HUMAN_REVIEW
            analysis.human_review_reason = (
                f"draft not allowed for category {analysis.category.value}"
            )
            analysis.action_reason = f"Escalated by policy: {analysis.human_review_reason}"
            analysis.reply_draft = None
        elif not analysis.reply_draft:
            analysis.suggested_action = SuggestedAction.HUMAN_REVIEW
            analysis.human_review_reason = "model chose draft_reply but produced no draft"
            analysis.action_reason = f"Escalated by policy: {analysis.human_review_reason}"

    return analysis
