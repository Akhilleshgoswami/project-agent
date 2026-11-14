"""Shared helpers for structured LLM calls."""

from __future__ import annotations

from typing import Any

from support_agent.cost import usage_from_tokens
from support_agent.schema import UsageStats
from support_agent.settings import Settings


def usage_from_structured_raw(raw: dict[str, Any], settings: Settings) -> UsageStats:
    raw_msg = raw.get("raw")
    meta = getattr(raw_msg, "usage_metadata", None) or {}
    if meta:
        return usage_from_tokens(
            int(meta.get("input_tokens") or meta.get("prompt_tokens") or 0),
            int(meta.get("output_tokens") or meta.get("completion_tokens") or 0),
            settings,
        )
    resp_meta = getattr(raw_msg, "response_metadata", None) or {}
    token_usage = resp_meta.get("token_usage") or {}
    return usage_from_tokens(
        int(token_usage.get("prompt_tokens") or 0),
        int(token_usage.get("completion_tokens") or 0),
        settings,
    )
