from support_agent.guardrail import DryRunGuardrail, apply_guardrail_verdict
from support_agent.schema import (
    GuardrailDecision,
    GuardrailVerdict,
    Priority,
    SuggestedAction,
    TicketAnalysis,
    TicketCategory,
    TicketInput,
)
from support_agent.settings import Settings


def _analysis(**overrides) -> TicketAnalysis:
    base = {
        "category": TicketCategory.QUESTION,
        "priority": Priority.LOW,
        "priority_reason": "faq",
        "confidence": 0.9,
        "suggested_action": SuggestedAction.DRAFT_REPLY,
        "action_reason": "simple",
        "reply_draft": "Here is how.",
    }
    base.update(overrides)
    return TicketAnalysis(**base)


def test_apply_allow_draft():
    verdict = GuardrailVerdict(
        decision=GuardrailDecision.ALLOW_DRAFT,
        reasons=["safe FAQ"],
        risk_flags=[],
        confidence=0.95,
    )
    updated = apply_guardrail_verdict(_analysis(), verdict, confidence_threshold=0.75)
    assert updated.suggested_action == SuggestedAction.DRAFT_REPLY
    assert updated.reply_draft


def test_apply_escalate_clears_sensitive_draft():
    verdict = GuardrailVerdict(
        decision=GuardrailDecision.ESCALATE,
        reasons=["refund requested"],
        risk_flags=["refund"],
        confidence=0.9,
    )
    updated = apply_guardrail_verdict(_analysis(), verdict, confidence_threshold=0.75)
    assert updated.suggested_action == SuggestedAction.HUMAN_REVIEW
    assert updated.reply_draft is None
    assert "refund" in (updated.human_review_reason or "")


def test_hard_confidence_floor_overrides_allow():
    verdict = GuardrailVerdict(
        decision=GuardrailDecision.ALLOW_DRAFT,
        reasons=["looks fine"],
        risk_flags=[],
        confidence=0.9,
    )
    updated = apply_guardrail_verdict(
        _analysis(confidence=0.4),
        verdict,
        confidence_threshold=0.75,
    )
    assert updated.suggested_action == SuggestedAction.HUMAN_REVIEW


def test_dry_run_guardrail_blocks_refund():
    settings = Settings(openai_api_key="", confidence_threshold=0.75)
    rail = DryRunGuardrail(settings)
    ticket = TicketInput(
        ticket_id="T002",
        subject="Charged twice",
        message="Please refund the duplicate charge.",
    )
    analysis = _analysis(
        category=TicketCategory.BILLING,
        suggested_action=SuggestedAction.DRAFT_REPLY,
        reply_draft="We refunded you.",
    )
    updated, verdict, usage = rail.review(ticket, analysis)
    assert verdict.decision == GuardrailDecision.ESCALATE
    assert updated.suggested_action == SuggestedAction.HUMAN_REVIEW
    assert usage.total_tokens == 0
