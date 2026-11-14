"""Human-in-the-loop helpers: apply decisions and interactive CLI prompts."""

from __future__ import annotations

from support_agent.schema import (
    DecisionLogEntry,
    HumanDecision,
    HumanDecisionAction,
    SuggestedAction,
    TicketAnalysis,
)


def apply_human_decision(
    analysis: TicketAnalysis,
    decision: HumanDecision,
) -> tuple[TicketAnalysis, DecisionLogEntry]:
    """Mutate analysis according to approve / edit / reject."""
    updated = analysis.model_copy(deep=True)

    if decision.action == HumanDecisionAction.AUTO_APPROVE:
        if not updated.reply_draft:
            raise ValueError("Cannot auto-approve: no reply draft present")
        detail = decision.note or "Supervision auto-approved draft reply"
        return updated, DecisionLogEntry(step="supervision", detail=detail)

    if decision.action == HumanDecisionAction.AUTO_ESCALATE:
        reason = decision.note or "Supervision withheld auto-reply; queued for human"
        # Keep draft text for the human queue, but do not treat as send-ready.
        kept_draft = updated.reply_draft
        updated.suggested_action = SuggestedAction.HUMAN_REVIEW
        updated.human_review_reason = reason
        updated.action_reason = f"Supervisor escalated: {reason}"
        updated.reply_draft = kept_draft  # attach as suggested draft for the agent
        return updated, DecisionLogEntry(step="supervision", detail=f"auto-escalated: {reason}")

    if decision.action == HumanDecisionAction.APPROVE:
        if not updated.reply_draft:
            raise ValueError("Cannot approve: no reply draft present")
        detail = "Human approved draft reply"
        if decision.note:
            detail += f" ({decision.note})"
        return updated, DecisionLogEntry(step="hitl", detail=detail)

    if decision.action == HumanDecisionAction.EDIT:
        edited = (decision.edited_draft or "").strip()
        if not edited:
            raise ValueError("Edit requires a non-empty edited_draft")
        updated.reply_draft = edited
        updated.suggested_action = SuggestedAction.DRAFT_REPLY
        updated.action_reason = "Human edited and approved the draft reply"
        updated.human_review_reason = None
        detail = "Human edited draft reply"
        if decision.note:
            detail += f" ({decision.note})"
        return updated, DecisionLogEntry(step="hitl", detail=detail)

    if decision.action == HumanDecisionAction.REJECT:
        updated.suggested_action = SuggestedAction.HUMAN_REVIEW
        updated.reply_draft = None
        reason = decision.note or "Human rejected auto-reply draft"
        updated.human_review_reason = reason
        updated.action_reason = f"Escalated after HITL reject: {reason}"
        return updated, DecisionLogEntry(step="hitl", detail=f"Human rejected draft: {reason}")

    raise ValueError(f"Unknown HITL action: {decision.action}")


def prompt_human_decision(payload: dict) -> HumanDecision:
    """Interactive CLI: approve / edit / reject a draft."""
    print("\n--- Human review required (draft reply) ---")
    print(f"Ticket:  {payload.get('ticket_id')}")
    if payload.get("thread_id"):
        print(f"Thread:  {payload.get('thread_id')}")
    print(f"Subject: {payload.get('subject')}")
    print(f"Category/Priority: {payload.get('category')} / {payload.get('priority')}")
    print(f"Confidence: {payload.get('confidence')}")
    if payload.get("review_mode"):
        print(f"Mode: {payload.get('review_mode')}")
    if payload.get("supervision_reason"):
        print(f"Why paused: {payload.get('supervision_reason')}")
    print("\nCustomer message:")
    print(payload.get("message", ""))
    print("\nProposed draft:")
    print(payload.get("reply_draft") or "(empty)")
    print("\nChoose: [a]pprove  [e]dit  [r]eject")

    while True:
        choice = input("> ").strip().lower()
        if choice in {"a", "approve"}:
            note = input("Optional note (Enter to skip): ").strip() or None
            return HumanDecision(action=HumanDecisionAction.APPROVE, note=note)
        if choice in {"e", "edit"}:
            print("Enter edited draft. Finish with a blank line:")
            lines: list[str] = []
            while True:
                line = input()
                if line == "" and lines:
                    break
                lines.append(line)
            edited = "\n".join(lines).strip()
            if not edited:
                print("Draft was empty; try again.")
                continue
            note = input("Optional note (Enter to skip): ").strip() or None
            return HumanDecision(
                action=HumanDecisionAction.EDIT,
                edited_draft=edited,
                note=note,
            )
        if choice in {"r", "reject"}:
            note = input("Reject reason (required): ").strip()
            if not note:
                print("A reason is required for reject.")
                continue
            return HumanDecision(action=HumanDecisionAction.REJECT, note=note)
        print("Please enter a, e, or r.")
