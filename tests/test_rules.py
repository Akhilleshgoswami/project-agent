from support_agent.rules import apply_escalation_policy, find_sensitive_match
from support_agent.schema import (
    Priority,
    SuggestedAction,
    TicketAnalysis,
    TicketCategory,
    TicketInput,
)


def _ticket(subject: str, message: str, ticket_id: str = "T999") -> TicketInput:
    return TicketInput(ticket_id=ticket_id, subject=subject, message=message)


def _analysis(**overrides) -> TicketAnalysis:
    base = {
        "category": TicketCategory.QUESTION,
        "priority": Priority.LOW,
        "priority_reason": "test",
        "confidence": 0.9,
        "suggested_action": SuggestedAction.DRAFT_REPLY,
        "action_reason": "simple how-to",
        "reply_draft": "Here is how…",
        "human_review_reason": None,
    }
    base.update(overrides)
    return TicketAnalysis(**base)


def test_sensitive_refund_detected():
    t = _ticket("Need refund", "Please refund my last payment.")
    assert find_sensitive_match(t) == "refund / money movement"


def test_low_confidence_forces_escalation():
    t = _ticket("How do I export?", "Where is the export button?")
    result = apply_escalation_policy(t, _analysis(confidence=0.4), confidence_threshold=0.75)
    assert result.suggested_action == SuggestedAction.HUMAN_REVIEW
    assert result.reply_draft is None
    assert "confidence" in (result.human_review_reason or "")


def test_phishing_forces_escalation():
    t = _ticket("Weird email", "They asked for my wallet seed phrase.")
    result = apply_escalation_policy(t, _analysis(confidence=0.95), confidence_threshold=0.75)
    assert result.suggested_action == SuggestedAction.HUMAN_REVIEW
    assert "phishing" in (result.human_review_reason or "").lower() or "security" in (
        result.human_review_reason or ""
    ).lower()


def test_simple_question_keeps_draft():
    t = _ticket("Keyboard shortcut", "Is there a shortcut for search?")
    result = apply_escalation_policy(t, _analysis(), confidence_threshold=0.75)
    assert result.suggested_action == SuggestedAction.DRAFT_REPLY
    assert result.reply_draft


def test_draft_not_allowed_for_bug():
    t = _ticket("App crash", "The app crashes on launch.")
    result = apply_escalation_policy(
        t,
        _analysis(
            category=TicketCategory.BUG,
            suggested_action=SuggestedAction.DRAFT_REPLY,
            reply_draft="Please restart.",
        ),
        confidence_threshold=0.75,
    )
    assert result.suggested_action == SuggestedAction.HUMAN_REVIEW
    assert result.reply_draft is None


def test_missing_draft_escalates():
    t = _ticket("How to?", "How do I rotate keys?")
    result = apply_escalation_policy(
        t,
        _analysis(reply_draft=None),
        confidence_threshold=0.75,
    )
    assert result.suggested_action == SuggestedAction.HUMAN_REVIEW
