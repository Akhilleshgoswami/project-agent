from support_agent.dry_run import DryRunClassifier
from support_agent.graph import process_ticket
from support_agent.guardrail import DryRunGuardrail
from support_agent.io import load_tickets
from support_agent.schema import (
    HumanDecision,
    HumanDecisionAction,
    Priority,
    ReviewMode,
    SuggestedAction,
    TicketAnalysis,
    TicketCategory,
)
from support_agent.settings import Settings
from support_agent.supervision import needs_human_supervision


def _draft(**overrides) -> TicketAnalysis:
    base = {
        "category": TicketCategory.QUESTION,
        "priority": Priority.LOW,
        "priority_reason": "faq",
        "confidence": 0.95,
        "suggested_action": SuggestedAction.DRAFT_REPLY,
        "action_reason": "simple",
        "reply_draft": "Here is how.",
    }
    base.update(overrides)
    return TicketAnalysis(**base)


def test_auto_approve_high_confidence_question():
    needs, reason = needs_human_supervision(_draft(), auto_approve_threshold=0.90)
    assert needs is False
    assert "auto-approved" in reason


def test_needs_human_when_confidence_borderline():
    needs, reason = needs_human_supervision(
        _draft(confidence=0.82),
        auto_approve_threshold=0.90,
    )
    assert needs is True
    assert "below auto-approve" in reason


def test_needs_human_when_priority_high():
    needs, reason = needs_human_supervision(
        _draft(priority=Priority.HIGH, confidence=0.99),
        auto_approve_threshold=0.90,
    )
    assert needs is True
    assert "priority" in reason


def test_graph_supervision_auto_approves_praise():
    tickets = load_tickets("data/tickets.csv")
    ticket = next(t for t in tickets if t.ticket_id == "T029")
    settings = Settings(
        openai_api_key="",
        confidence_threshold=0.75,
        auto_approve_threshold=0.90,
    )
    called = {"n": 0}

    def should_not_run(_payload: dict) -> HumanDecision:
        called["n"] += 1
        return HumanDecision(action=HumanDecisionAction.APPROVE)

    result = process_ticket(
        ticket,
        settings=settings,
        classifier=DryRunClassifier(),
        guardrail=DryRunGuardrail(settings),
        review_mode=ReviewMode.SUPERVISION,
        hitl_handler=should_not_run,
    )
    assert called["n"] == 0
    assert result.suggested_action == SuggestedAction.DRAFT_REPLY
    assert result.human_decision is not None
    assert result.human_decision.action == HumanDecisionAction.AUTO_APPROVE
    assert result.human_decision.source == "supervision"


def test_graph_supervision_auto_escalates_borderline_without_prompt():
    # Dry-run T004 confidence 0.80 → supervisor escalates; no interactive handler call
    tickets = load_tickets("data/tickets.csv")
    ticket = next(t for t in tickets if t.ticket_id == "T004")
    settings = Settings(
        openai_api_key="",
        confidence_threshold=0.75,
        auto_approve_threshold=0.90,
    )
    called = {"n": 0}

    def should_not_run(_payload: dict) -> HumanDecision:
        called["n"] += 1
        return HumanDecision(action=HumanDecisionAction.APPROVE)

    result = process_ticket(
        ticket,
        settings=settings,
        classifier=DryRunClassifier(),
        guardrail=DryRunGuardrail(settings),
        review_mode=ReviewMode.SUPERVISION,
        hitl_handler=should_not_run,
    )
    assert called["n"] == 0
    assert result.suggested_action == SuggestedAction.HUMAN_REVIEW
    assert result.human_decision.action == HumanDecisionAction.AUTO_ESCALATE
    assert result.reply_draft  # draft kept for the human queue
    assert any(e.step == "supervision" for e in result.decision_log)
