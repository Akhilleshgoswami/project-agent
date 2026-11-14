"""Token usage and rough cost estimation for gpt-4o-mini-class models."""

from __future__ import annotations

from support_agent.schema import UsageStats
from support_agent.settings import Settings, get_settings


def estimate_cost_usd(
    prompt_tokens: int,
    completion_tokens: int,
    settings: Settings | None = None,
) -> float:
    s = settings or get_settings()
    return (
        prompt_tokens * s.input_price_per_1m / 1_000_000
        + completion_tokens * s.output_price_per_1m / 1_000_000
    )


def usage_from_tokens(
    prompt_tokens: int,
    completion_tokens: int,
    settings: Settings | None = None,
) -> UsageStats:
    total = prompt_tokens + completion_tokens
    return UsageStats(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total,
        estimated_cost_usd=estimate_cost_usd(prompt_tokens, completion_tokens, settings),
    )


def merge_usage(a: UsageStats, b: UsageStats) -> UsageStats:
    prompt = a.prompt_tokens + b.prompt_tokens
    completion = a.completion_tokens + b.completion_tokens
    return UsageStats(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        estimated_cost_usd=a.estimated_cost_usd + b.estimated_cost_usd,
    )


def cost_per_100_tickets(total_cost_usd: float, ticket_count: int) -> float:
    if ticket_count <= 0:
        return 0.0
    return (total_cost_usd / ticket_count) * 100
