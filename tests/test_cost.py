from support_agent.cost import cost_per_100_tickets, estimate_cost_usd, merge_usage
from support_agent.schema import UsageStats
from support_agent.settings import Settings


def test_estimate_cost_usd():
    s = Settings(openai_api_key="x", input_price_per_1m=0.15, output_price_per_1m=0.60)
    # 1M prompt + 1M completion → 0.15 + 0.60 = 0.75
    assert estimate_cost_usd(1_000_000, 1_000_000, s) == 0.75


def test_cost_per_100():
    assert cost_per_100_tickets(0.05, 10) == 0.5
    assert cost_per_100_tickets(1.0, 0) == 0.0


def test_merge_usage():
    a = UsageStats(prompt_tokens=10, completion_tokens=5, total_tokens=15, estimated_cost_usd=0.01)
    b = UsageStats(prompt_tokens=20, completion_tokens=5, total_tokens=25, estimated_cost_usd=0.02)
    m = merge_usage(a, b)
    assert m.prompt_tokens == 30
    assert m.completion_tokens == 10
    assert m.total_tokens == 40
    assert abs(m.estimated_cost_usd - 0.03) < 1e-9
