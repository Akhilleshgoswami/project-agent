"""Heuristic classifier for offline dry-runs (no API key)."""

from __future__ import annotations

import re

from support_agent.schema import (
    Priority,
    SuggestedAction,
    TicketAnalysis,
    TicketCategory,
    TicketInput,
    UsageStats,
)


def _text(ticket: TicketInput) -> str:
    return f"{ticket.subject}\n{ticket.message}".lower()


class DryRunClassifier:
    """Keyword heuristic that exercises the same graph + policy path."""

    def classify(self, ticket: TicketInput) -> tuple[TicketAnalysis, UsageStats]:
        text = _text(ticket)

        if re.search(r"phish|seed phrase|wallet", text):
            category = TicketCategory.OTHER
            priority = Priority.CRITICAL
            action = SuggestedAction.HUMAN_REVIEW
            draft = None
            conf = 0.55
            reason = "Possible security/phishing report"
        elif re.search(r"thank|excellent|no action needed|keep it up", text):
            category = TicketCategory.OTHER
            priority = Priority.LOW
            action = SuggestedAction.DRAFT_REPLY
            draft = (
                "Thank you for the kind note — we are glad the onboarding checklist "
                "is helping. We will pass this along to the product team."
            )
            conf = 0.9
            reason = "Praise with no action required"
        elif re.search(r"refund|charged|invoice|subscription|billing|seats|payment", text):
            category = TicketCategory.BILLING
            priority = Priority.HIGH if "refund" in text or "twice" in text else Priority.MEDIUM
            action = SuggestedAction.HUMAN_REVIEW
            draft = None
            conf = 0.85
            reason = "Billing topic needs human handling"
        elif re.search(r"feature|would love|please add|would be great|dark mode", text):
            category = TicketCategory.FEATURE_REQUEST
            priority = Priority.LOW
            action = SuggestedAction.HUMAN_REVIEW
            draft = None
            conf = 0.8
            reason = "Feature request for product backlog"
        elif re.search(
            r"crash|500|error|bug|broken|loop|fails|blank|logout|nothing happens",
            text,
        ):
            category = TicketCategory.BUG
            priority = (
                Priority.CRITICAL
                if re.search(r"down|urgent|go-live|production|tenant", text)
                else Priority.HIGH
            )
            action = SuggestedAction.HUMAN_REVIEW
            draft = None
            conf = 0.85
            reason = "Suspected product defect needs engineering"
        elif re.search(r"how |what is|where |docs|shortcut|policy|scim|\?", text):
            category = TicketCategory.QUESTION
            priority = Priority.MEDIUM
            action = SuggestedAction.DRAFT_REPLY
            draft = (
                f"Thanks for reaching out about \"{ticket.subject}\". "
                "You can usually find this in our Help Center under Account & Security "
                "or Billing. If that does not answer it, reply here and a teammate "
                "will follow up."
            )
            conf = 0.8
            reason = "Simple how-to / FAQ-style question"
        else:
            category = TicketCategory.OTHER
            priority = Priority.MEDIUM
            action = SuggestedAction.HUMAN_REVIEW
            draft = None
            conf = 0.5
            reason = "Unclear intent"

        analysis = TicketAnalysis(
            category=category,
            priority=priority,
            priority_reason=reason,
            confidence=conf,
            suggested_action=action,
            action_reason=reason,
            reply_draft=draft,
            human_review_reason=None if action == SuggestedAction.DRAFT_REPLY else reason,
        )
        return analysis, UsageStats()
