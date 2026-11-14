from support_agent.dry_run import DryRunClassifier
from support_agent.graph import process_ticket
from support_agent.guardrail import DryRunGuardrail
from support_agent.hitl import apply_human_decision
from support_agent.io import load_tickets
from support_agent.schema import (
    HumanDecision,
    HumanDecisionAction,
    Priority,
    ReviewMode,
    SuggestedAction,
    TicketAnalysis,
    TicketCategory,
    TicketInput,
)
from support_agent.settings import Settings


def _analysis_with_draft() -> TicketAnalysis:
    return TicketAnalysis(
        category=TicketCategory.QUESTION,
        priority=Priority.LOW,
        priority_reason="faq",
        confidence=0.9,
        suggested_action=SuggestedAction.DRAFT_REPLY,
        action_reason="simple",
        reply_draft="Here is how to reset your password.",
    )


def test_apply_approve():
    updated, log = apply_human_decision(
        _analysis_with_draft(),
        HumanDecision(action=HumanDecisionAction.APPROVE),
    )
    assert updated.suggested_action == SuggestedAction.DRAFT_REPLY
    assert updated.reply_draft
    assert log.step == "hitl"


def test_apply_edit():
    updated, log = apply_human_decision(
        _analysis_with_draft(),
        HumanDecision(action=HumanDecisionAction.EDIT, edited_draft="Edited reply."),
    )
    assert updated.reply_draft == "Edited reply."
    assert updated.suggested_action == SuggestedAction.DRAFT_REPLY
    assert "edited" in log.detail.lower()


def test_apply_reject():
    updated, log = apply_human_decision(
        _analysis_with_draft(),
        HumanDecision(action=HumanDecisionAction.REJECT, note="Tone wrong"),
    )
    assert updated.suggested_action == SuggestedAction.HUMAN_REVIEW
    assert updated.reply_draft is None
    assert "Tone wrong" in (updated.human_review_reason or "")
    assert log.step == "hitl"


def test_graph_hitl_approve_on_question():
    tickets = load_tickets("data/tickets.csv")
    ticket = next(t for t in tickets if t.ticket_id == "T004")
    settings = Settings(openai_api_key="", confidence_threshold=0.75)

    def auto_approve(payload: dict) -> HumanDecision:
        assert payload["ticket_id"] == "T004"
        assert payload["reply_draft"]
        return HumanDecision(action=HumanDecisionAction.APPROVE, note="looks good")

    result = process_ticket(
        ticket,
        settings=settings,
        classifier=DryRunClassifier(),
        guardrail=DryRunGuardrail(settings),
        review_mode=ReviewMode.HITL,
        hitl_handler=auto_approve,
    )
    assert result.suggested_action == SuggestedAction.DRAFT_REPLY
    assert result.human_decision is not None
    assert result.human_decision.action == HumanDecisionAction.APPROVE
    assert any(e.step == "hitl" for e in result.decision_log)
    assert any(e.step == "guardrail" for e in result.decision_log)


def test_graph_hitl_reject_escalates():
    ticket = TicketInput(
        ticket_id="T004",
        subject="How do I reset my password?",
        message="Is there a reset link on the login page?",
    )
    settings = Settings(openai_api_key="", confidence_threshold=0.75)

    def reject(_payload: dict) -> HumanDecision:
        return HumanDecision(action=HumanDecisionAction.REJECT, note="needs SSO nuance")

    result = process_ticket(
        ticket,
        settings=settings,
        classifier=DryRunClassifier(),
        guardrail=DryRunGuardrail(settings),
        review_mode=ReviewMode.HITL,
        hitl_handler=reject,
    )
    assert result.suggested_action == SuggestedAction.HUMAN_REVIEW
    assert result.reply_draft is None
    assert result.human_decision.action == HumanDecisionAction.REJECT


def test_graph_skips_hitl_for_escalated_bug():
    tickets = load_tickets("data/tickets.csv")
    ticket = next(t for t in tickets if t.ticket_id == "T001")
    settings = Settings(openai_api_key="", confidence_threshold=0.75)
    called = {"n": 0}

    def should_not_run(_payload: dict) -> HumanDecision:
        called["n"] += 1
        return HumanDecision(action=HumanDecisionAction.APPROVE)

    result = process_ticket(
        ticket,
        settings=settings,
        classifier=DryRunClassifier(),
        guardrail=DryRunGuardrail(settings),
        review_mode=ReviewMode.HITL,
        hitl_handler=should_not_run,
    )
    assert called["n"] == 0
    assert result.suggested_action == SuggestedAction.HUMAN_REVIEW
    assert result.human_decision is None
