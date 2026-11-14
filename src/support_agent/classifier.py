"""LLM structured classification for a single ticket."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from support_agent.llm_utils import usage_from_structured_raw
from support_agent.prompts import CLASSIFICATION_PROMPT
from support_agent.schema import TicketAnalysis, TicketInput, UsageStats
from support_agent.settings import Settings, get_settings


class TicketClassifier:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        api_key = self.settings.resolved_api_key()
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key, "
                "or pass --dry-run for an offline heuristic run."
            )
        self.llm = ChatOpenAI(
            model=self.settings.model_name,
            temperature=0.0,
            api_key=api_key,
        )
        self.structured_llm = self.llm.with_structured_output(
            TicketAnalysis,
            include_raw=True,
        )

    def classify(self, ticket: TicketInput) -> tuple[TicketAnalysis, UsageStats]:
        messages = [
            SystemMessage(content=CLASSIFICATION_PROMPT),
            HumanMessage(
                content=(
                    f"Ticket ID: {ticket.ticket_id}\n\n"
                    f"Subject: {ticket.subject}\n\n"
                    f"Message: {ticket.message}"
                )
            ),
        ]
        raw: dict[str, Any] = self.structured_llm.invoke(messages)
        analysis: TicketAnalysis = raw["parsed"]
        if analysis is None:
            parsing_error = raw.get("parsing_error")
            raise RuntimeError(f"Failed to parse model output: {parsing_error}")
        return analysis, usage_from_structured_raw(raw, self.settings)
