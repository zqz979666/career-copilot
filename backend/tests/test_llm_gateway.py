"""LLM Gateway smoke tests — cost calculation, no network."""
from __future__ import annotations

from types import SimpleNamespace

from app.llm.gateway import LLMGateway


def test_pricing_sonnet_costs() -> None:
    gw = LLMGateway.__new__(LLMGateway)  # skip __init__ (no client needed)
    usage = LLMGateway._compute_usage(
        SimpleNamespace(
            input_tokens=1000,
            output_tokens=2000,
            cache_read_input_tokens=500,
            cache_creation_input_tokens=100,
        ),
        elapsed_s=1.234,
        model="claude-sonnet-4-5",
    )
    # 1000 * 3 + 2000 * 15 + 500 * 0.3 + 100 * 3.75 = 3 + 30 + 0.15 + 0.375 = 33.525 / 1e6 total
    expected = (
        1000 * 3.0 / 1_000_000
        + 2000 * 15.0 / 1_000_000
        + 500 * 0.3 / 1_000_000
        + 100 * 3.75 / 1_000_000
    )
    assert abs(usage.cost_usd - expected) < 1e-9
    assert usage.model == "claude-sonnet-4-5"
    assert usage.latency_ms == 1234.0


def test_pricing_falls_back_to_default_for_unknown_model() -> None:
    usage = LLMGateway._compute_usage(
        SimpleNamespace(input_tokens=100, output_tokens=0),
        elapsed_s=0.1,
        model="claude-neverheardof-9000",
    )
    # Falls back to Sonnet pricing
    assert usage.cost_usd == 100 * 3.0 / 1_000_000
