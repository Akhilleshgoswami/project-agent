"""Selective human supervision: auto-approve safe drafts, interrupt only when needed."""

from __future__ import annotations

from support_agent.schema import (
    Priority,
    SuggestedAction,
    TicketAnalysis,
    TicketCategory,
)


def needs_human_supervision(
    analysis: TicketAnalysis,
    *,
    auto_approve_threshold: float,
) -> tuple[bool, str]:
    """Return (needs_human, reason).

    High-confidence, low/medium-priority FAQ drafts can auto-approve.
    Borderline confidence, high/critical priority, or non-question drafts
    still require a human.
    """
    if analysis.suggested_action != SuggestedAction.DRAFT_REPLY or not analysis.reply_draft:
        return False, "no draft to supervise"

    if analysis.priority in (Priority.HIGH, Priority.CRITICAL):
        return True, f"priority {analysis.priority.value} requires human supervision"

    if analysis.category not in (TicketCategory.QUESTION, TicketCategory.OTHER):
        return True, f"category {analysis.category.value} drafts require human supervision"

    if analysis.confidence < auto_approve_threshold:
        reason = (
            f"confidence {analysis.confidence:.2f} below auto-approve "
            f"threshold {auto_approve_threshold:.2f}"
        )
        return True, reason

    reason = (
        f"auto-approved: confidence {analysis.confidence:.2f} >= "
        f"{auto_approve_threshold:.2f}, priority={analysis.priority.value}, "
        f"category={analysis.category.value}"
    )
    return False, reason
