"""LLM-based guardrail that allows or blocks auto-reply drafts."""

from __future__ import annotations

from typing import Any, Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from support_agent.llm_utils import usage_from_structured_raw
from support_agent.prompts import GUARDRAIL_PROMPT
from support_agent.rules import apply_escalation_policy
from support_agent.schema import (
    GuardrailDecision,
    GuardrailVerdict,
    SuggestedAction,
    TicketAnalysis,
    TicketInput,
    UsageStats,
)
from support_agent.settings import Settings, get_settings


class Guardrail(Protocol):
    def review(
        self,
        ticket: TicketInput,
        analysis: TicketAnalysis,
    ) -> tuple[TicketAnalysis, GuardrailVerdict, UsageStats]: ...


def apply_guardrail_verdict(
    analysis: TicketAnalysis,
    verdict: GuardrailVerdict,
    *,
    confidence_threshold: float,
) -> TicketAnalysis:
    """Apply verdict (+ hard confidence floor) onto the triage analysis."""
    updated = analysis.model_copy(deep=True)
    reasons = list(verdict.reasons)

    if updated.confidence < confidence_threshold:
        reasons.append(
            f"triage confidence {updated.confidence:.2f} below threshold "
            f"{confidence_threshold:.2f}"
        )
        verdict = verdict.model_copy(
            update={
                "decision": GuardrailDecision.ESCALATE,
                "reasons": reasons,
                "risk_flags": list(dict.fromkeys([*verdict.risk_flags, "low_confidence"])),
            }
        )

    if verdict.decision == GuardrailDecision.ALLOW_DRAFT:
        if updated.suggested_action != SuggestedAction.DRAFT_REPLY or not updated.reply_draft:
            updated.suggested_action = SuggestedAction.HUMAN_REVIEW
            updated.reply_draft = None
            updated.human_review_reason = "guardrail allow_draft but no usable draft present"
            updated.action_reason = f"Escalated by guardrail: {updated.human_review_reason}"
            return updated
        updated.suggested_action = SuggestedAction.DRAFT_REPLY
        updated.human_review_reason = None
        updated.action_reason = "Guardrail allowed draft: " + (
            "; ".join(verdict.reasons) or "safe FAQ-style reply"
        )
        return updated

    # escalate
    updated.suggested_action = SuggestedAction.HUMAN_REVIEW
    reason = "; ".join(reasons) or "guardrail escalated"
    if verdict.risk_flags:
        reason = f"{reason} [flags={','.join(verdict.risk_flags)}]"
    updated.human_review_reason = reason
    updated.action_reason = f"Escalated by LLM guardrail: {reason}"
    # Keep draft only as a suggestion for humans if one existed; still not send-ready.
    # For hard rejects on sensitive topics, clear it when risk flags demand.
    hard_clear = {
        "refund",
        "phishing",
        "legal",
        "account_access",
        "billing",
    }
    if hard_clear.intersection(verdict.risk_flags):
        updated.reply_draft = None
    return updated


class LLMGuardrail:
    """Structured-output LLM guardrail."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        api_key = self.settings.resolved_api_key()
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY is not set for LLM guardrail. "
                "Use --dry-run for the offline heuristic guardrail."
            )
        self.llm = ChatOpenAI(
            model=self.settings.model_name,
            temperature=0.0,
            api_key=api_key,
        )
        self.structured_llm = self.llm.with_structured_output(
            GuardrailVerdict,
            include_raw=True,
        )

    def review(
        self,
        ticket: TicketInput,
        analysis: TicketAnalysis,
    ) -> tuple[TicketAnalysis, GuardrailVerdict, UsageStats]:
        messages = [
            SystemMessage(content=GUARDRAIL_PROMPT),
            HumanMessage(
                content=(
                    f"Ticket ID: {ticket.ticket_id}\n"
                    f"Subject: {ticket.subject}\n"
                    f"Message: {ticket.message}\n\n"
                    f"Triage analysis JSON:\n{analysis.model_dump_json(indent=2)}"
                )
            ),
        ]
        raw: dict[str, Any] = self.structured_llm.invoke(messages)
        verdict: GuardrailVerdict | None = raw["parsed"]
        if verdict is None:
            raise RuntimeError(f"Failed to parse guardrail output: {raw.get('parsing_error')}")

        usage = usage_from_structured_raw(raw, self.settings)
        updated = apply_guardrail_verdict(
            analysis,
            verdict,
            confidence_threshold=self.settings.confidence_threshold,
        )
        return updated, verdict, usage


class DryRunGuardrail:
    """Offline stand-in: reuses deterministic rules as a guardrail proxy."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def review(
        self,
        ticket: TicketInput,
        analysis: TicketAnalysis,
    ) -> tuple[TicketAnalysis, GuardrailVerdict, UsageStats]:
        before = analysis.model_copy(deep=True)
        after = apply_escalation_policy(
            ticket,
            before,
            self.settings.confidence_threshold,
        )
        if after.suggested_action == SuggestedAction.DRAFT_REPLY and after.reply_draft:
            verdict = GuardrailVerdict(
                decision=GuardrailDecision.ALLOW_DRAFT,
                reasons=["dry-run heuristic: safe draft"],
                risk_flags=[],
                confidence=0.85,
            )
        else:
            reason = after.human_review_reason or after.action_reason or "escalated"
            flags: list[str] = []
            lowered = reason.lower()
            for tag in (
                "refund",
                "phishing",
                "billing",
                "legal",
                "account",
                "confidence",
                "draft",
            ):
                if tag in lowered:
                    flags.append("account_access" if tag == "account" else tag)
            verdict = GuardrailVerdict(
                decision=GuardrailDecision.ESCALATE,
                reasons=[reason],
                risk_flags=flags,
                confidence=0.85,
            )
        # Re-apply through shared applicator for consistent logging shape
        updated = apply_guardrail_verdict(
            analysis.model_copy(deep=True),
            verdict,
            confidence_threshold=self.settings.confidence_threshold,
        )
        # Prefer policy-cleared draft behavior from deterministic path
        if after.reply_draft is None:
            updated.reply_draft = None
        return updated, verdict, UsageStats()
