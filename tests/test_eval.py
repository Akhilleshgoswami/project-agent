from support_agent.eval import score_results
from support_agent.schema import (
    Priority,
    SuggestedAction,
    TicketCategory,
    TicketResult,
)


def test_score_results():
    results = [
        TicketResult(
            ticket_id="T001",
            thread_id="ticket-T001-run-x",
            run_id="x",
            subject="x",
            category=TicketCategory.BUG,
            priority=Priority.HIGH,
            priority_reason="r",
            confidence=0.9,
            suggested_action=SuggestedAction.HUMAN_REVIEW,
            action_reason="a",
        ),
        TicketResult(
            ticket_id="T004",
            thread_id="ticket-T004-run-x",
            run_id="x",
            subject="y",
            category=TicketCategory.QUESTION,
            priority=Priority.LOW,  # wrong vs medium
            priority_reason="r",
            confidence=0.9,
            suggested_action=SuggestedAction.DRAFT_REPLY,
            action_reason="a",
        ),
    ]
    labels = [
        {
            "ticket_id": "T001",
            "category": "bug",
            "priority": "high",
            "suggested_action": "human_review",
        },
        {
            "ticket_id": "T004",
            "category": "question",
            "priority": "medium",
            "suggested_action": "draft_reply",
        },
    ]
    scores = score_results(results, labels)
    assert scores.n == 2
    assert scores.category_accuracy == 1.0
    assert scores.priority_correct == 1
    assert scores.action_accuracy == 1.0
