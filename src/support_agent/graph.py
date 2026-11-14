"""LangGraph pipeline: classify → policy → (HITL / supervision) → finalize."""

from __future__ import annotations

import operator
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from support_agent.classifier import TicketClassifier
from support_agent.cost import merge_usage
from support_agent.guardrail import Guardrail, LLMGuardrail
from support_agent.hitl import apply_human_decision
from support_agent.schema import (
    DecisionLogEntry,
    HumanDecision,
    HumanDecisionAction,
    ReviewMode,
    SuggestedAction,
    TicketAnalysis,
    TicketInput,
    TicketResult,
    UsageStats,
)
from support_agent.settings import Settings, get_settings
from support_agent.supervision import needs_human_supervision

HitlHandler = Callable[[dict], HumanDecision]


class AgentState(TypedDict, total=False):
    ticket: TicketInput
    analysis: TicketAnalysis
    usage: UsageStats
    decision_log: Annotated[list[DecisionLogEntry], operator.add]
    human_decision: HumanDecision
    review_mode: str
    thread_id: str
    run_id: str
    result: TicketResult


def _checkpoint_serde() -> JsonPlusSerializer:
    allowed = [
        ("support_agent.schema", "TicketInput"),
        ("support_agent.schema", "TicketAnalysis"),
        ("support_agent.schema", "TicketResult"),
        ("support_agent.schema", "DecisionLogEntry"),
        ("support_agent.schema", "HumanDecision"),
        ("support_agent.schema", "UsageStats"),
        ("support_agent.schema", "TicketCategory"),
        ("support_agent.schema", "Priority"),
        ("support_agent.schema", "SuggestedAction"),
        ("support_agent.schema", "HumanDecisionAction"),
    ]
    return JsonPlusSerializer(allowed_msgpack_modules=allowed)


def build_graph(
    settings: Settings | None = None,
    classifier: TicketClassifier | None = None,
    guardrail: Guardrail | None = None,
    *,
    review_mode: ReviewMode = ReviewMode.OFF,
    checkpointer: MemorySaver | None = None,
):
    settings = settings or get_settings()
    clf = classifier or TicketClassifier(settings)
    rail = guardrail or LLMGuardrail(settings)

    def classify_node(state: AgentState) -> dict:
        ticket = state["ticket"]
        analysis, usage = clf.classify(ticket)
        log = [
            DecisionLogEntry(
                step="classify",
                detail=(
                    f"category={analysis.category.value} priority={analysis.priority.value} "
                    f"confidence={analysis.confidence:.2f} "
                    f"model_action={analysis.suggested_action.value}"
                ),
            )
        ]
        return {"analysis": analysis, "usage": usage, "decision_log": log}

    def guardrail_node(state: AgentState) -> dict:
        ticket = state["ticket"]
        before = state["analysis"]
        after, verdict, rail_usage = rail.review(ticket, before.model_copy(deep=True))
        changed = after.suggested_action != before.suggested_action
        detail = (
            f"decision={verdict.decision.value} action={after.suggested_action.value} "
            f"guardrail_conf={verdict.confidence:.2f}"
        )
        if changed:
            detail += f" (overridden from {before.suggested_action.value})"
        if verdict.reasons:
            detail += f" reasons={'; '.join(verdict.reasons)}"
        if verdict.risk_flags:
            detail += f" flags={','.join(verdict.risk_flags)}"
        prev_usage = state.get("usage") or UsageStats()
        return {
            "analysis": after,
            "usage": merge_usage(prev_usage, rail_usage),
            "decision_log": [DecisionLogEntry(step="guardrail", detail=detail)],
        }

    def route_after_policy(state: AgentState) -> str:
        mode = ReviewMode(state.get("review_mode") or ReviewMode.OFF.value)
        analysis = state["analysis"]
        has_draft = (
            analysis.suggested_action == SuggestedAction.DRAFT_REPLY and bool(analysis.reply_draft)
        )
        if not has_draft or mode == ReviewMode.OFF:
            return "finalize"

        if mode == ReviewMode.HITL:
            return "human_gate"

        # SUPERVISION is fully automatic — never pauses for keyboard input.
        needs_human, _reason = needs_human_supervision(
            analysis,
            auto_approve_threshold=settings.auto_approve_threshold,
        )
        return "auto_escalate" if needs_human else "auto_approve"

    def auto_approve_node(state: AgentState) -> dict:
        analysis = state["analysis"]
        _, reason = needs_human_supervision(
            analysis,
            auto_approve_threshold=settings.auto_approve_threshold,
        )
        decision = HumanDecision(
            action=HumanDecisionAction.AUTO_APPROVE,
            note=reason,
            source="supervision",
        )
        updated, log_entry = apply_human_decision(analysis, decision)
        return {
            "analysis": updated,
            "human_decision": decision,
            "decision_log": [log_entry],
        }

    def auto_escalate_node(state: AgentState) -> dict:
        analysis = state["analysis"]
        _, reason = needs_human_supervision(
            analysis,
            auto_approve_threshold=settings.auto_approve_threshold,
        )
        decision = HumanDecision(
            action=HumanDecisionAction.AUTO_ESCALATE,
            note=reason,
            source="supervision",
        )
        updated, log_entry = apply_human_decision(analysis, decision)
        return {
            "analysis": updated,
            "human_decision": decision,
            "decision_log": [log_entry],
        }

    def human_gate_node(state: AgentState) -> dict:
        ticket = state["ticket"]
        analysis = state["analysis"]
        mode = state.get("review_mode") or ReviewMode.HITL.value
        _, supervision_reason = needs_human_supervision(
            analysis,
            auto_approve_threshold=settings.auto_approve_threshold,
        )
        payload = {
            "ticket_id": ticket.ticket_id,
            "thread_id": state.get("thread_id"),
            "run_id": state.get("run_id"),
            "subject": ticket.subject,
            "message": ticket.message,
            "category": analysis.category.value,
            "priority": analysis.priority.value,
            "confidence": analysis.confidence,
            "reply_draft": analysis.reply_draft,
            "review_mode": mode,
            "supervision_reason": supervision_reason,
            "instructions": "Respond with approve | edit | reject",
        }
        raw: Any = interrupt(payload)
        if isinstance(raw, HumanDecision):
            decision = raw
        elif isinstance(raw, dict):
            decision = HumanDecision.model_validate(raw)
        else:
            raise TypeError(f"Unexpected HITL resume payload: {type(raw)}")

        if decision.source == "human" and decision.action == HumanDecisionAction.AUTO_APPROVE:
            # Humans should use approve; keep source honest if mis-sent
            decision = decision.model_copy(update={"action": HumanDecisionAction.APPROVE})

        updated, log_entry = apply_human_decision(analysis, decision)
        return {
            "analysis": updated,
            "human_decision": decision,
            "decision_log": [log_entry],
        }

    def finalize_node(state: AgentState) -> dict:
        ticket = state["ticket"]
        analysis = state["analysis"]
        usage = state.get("usage") or UsageStats()
        logs = list(state.get("decision_log") or [])
        human_decision = state.get("human_decision")
        thread_id = state.get("thread_id") or f"ticket-{ticket.ticket_id}"
        run_id = state.get("run_id") or "unknown"

        if analysis.suggested_action == SuggestedAction.DRAFT_REPLY:
            action_entry = DecisionLogEntry(
                step="draft",
                detail="Keeping customer reply draft for simple/safe question",
            )
        else:
            action_entry = DecisionLogEntry(
                step="escalate",
                detail=analysis.human_review_reason or analysis.action_reason,
            )
        logs.append(action_entry)

        finalize_entry = DecisionLogEntry(
            step="finalize",
            detail=f"logged ticket {ticket.ticket_id} thread_id={thread_id}",
        )
        logs.append(finalize_entry)

        result = TicketResult(
            ticket_id=ticket.ticket_id,
            thread_id=thread_id,
            run_id=run_id,
            subject=ticket.subject,
            category=analysis.category,
            priority=analysis.priority,
            priority_reason=analysis.priority_reason,
            confidence=analysis.confidence,
            suggested_action=analysis.suggested_action,
            action_reason=analysis.action_reason,
            reply_draft=analysis.reply_draft,
            human_review_reason=analysis.human_review_reason,
            human_decision=human_decision,
            decision_log=logs,
            usage=usage,
        )
        return {"result": result, "decision_log": [action_entry, finalize_entry]}

    graph = StateGraph(AgentState)
    graph.add_node("classify", classify_node)
    graph.add_node("guardrail", guardrail_node)
    graph.add_node("auto_approve", auto_approve_node)
    graph.add_node("auto_escalate", auto_escalate_node)
    graph.add_node("human_gate", human_gate_node)
    graph.add_node("finalize", finalize_node)
    graph.add_edge(START, "classify")
    graph.add_edge("classify", "guardrail")
    graph.add_conditional_edges(
        "guardrail",
        route_after_policy,
        {
            "human_gate": "human_gate",
            "auto_approve": "auto_approve",
            "auto_escalate": "auto_escalate",
            "finalize": "finalize",
        },
    )
    graph.add_edge("auto_approve", "finalize")
    graph.add_edge("auto_escalate", "finalize")
    graph.add_edge("human_gate", "finalize")
    graph.add_edge("finalize", END)

    saver = checkpointer or MemorySaver(serde=_checkpoint_serde())
    return graph.compile(checkpointer=saver)


def _extract_interrupt_payload(invoke_result: dict | Any) -> dict | None:
    interrupts = None
    if isinstance(invoke_result, dict):
        interrupts = invoke_result.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    value = getattr(first, "value", first)
    return value if isinstance(value, dict) else {"raw": value}


def process_ticket(
    ticket: TicketInput,
    settings: Settings | None = None,
    classifier: TicketClassifier | None = None,
    guardrail: Guardrail | None = None,
    *,
    enable_hitl: bool = False,
    review_mode: ReviewMode | None = None,
    hitl_handler: HitlHandler | None = None,
    run_id: str | None = None,
    thread_id: str | None = None,
    checkpointer: MemorySaver | None = None,
) -> TicketResult:
    """Run one ticket under a LangGraph thread_id you can refer to later.

    review_mode:
      - off: no review gate
      - hitl: every draft pauses for interactive human approve/edit/reject
      - supervision: fully automatic — auto-approve safe drafts, else queue for humans
    """
    from support_agent.hitl import prompt_human_decision
    from support_agent.threads import make_thread_id, new_run_id

    if review_mode is None:
        review_mode = ReviewMode.HITL if enable_hitl else ReviewMode.OFF

    run_id = run_id or new_run_id()
    thread_id = thread_id or make_thread_id(ticket.ticket_id, run_id)
    saver = checkpointer or MemorySaver(serde=_checkpoint_serde())

    app = build_graph(
        settings=settings,
        classifier=classifier,
        guardrail=guardrail,
        review_mode=review_mode,
        checkpointer=saver,
    )
    initial: AgentState = {
        "ticket": ticket,
        "decision_log": [],
        "review_mode": review_mode.value,
        "thread_id": thread_id,
        "run_id": run_id,
    }
    config = {"configurable": {"thread_id": thread_id}}

    # Supervision and off never interrupt — supervisor decides alone.
    if review_mode != ReviewMode.HITL:
        final = app.invoke(initial, config)
        return final["result"]

    handler = hitl_handler or prompt_human_decision

    result = app.invoke(initial, config)
    payload = _extract_interrupt_payload(result)
    while payload is not None:
        decision = handler(payload)
        result = app.invoke(Command(resume=decision.model_dump()), config)
        payload = _extract_interrupt_payload(result)

    if "result" not in result:
        snap = app.get_state(config)
        if snap.values.get("result"):
            return snap.values["result"]
        raise RuntimeError(f"HITL run did not produce a result for {ticket.ticket_id}")
    return result["result"]
