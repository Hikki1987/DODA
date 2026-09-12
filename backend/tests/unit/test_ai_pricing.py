"""Unit tests for `doda.infrastructure.ai_pricing` — no DB, no network;
pure arithmetic on the MODEL_PRICING table plus the char->token heuristic
that gates every budget reservation (`doda.application.ai_budget_service`).
"""

import pytest

from doda.ai.types import Provider
from doda.infrastructure.ai_pricing import (
    UnknownModelPricingError,
    estimate_cost_cents,
    estimate_input_tokens_from_chars,
)


def test_cost_is_computed_separately_for_input_and_output_tokens() -> None:
    # gpt-5-mini: $0.25/1M input, $2.00/1M output.
    cents = estimate_cost_cents(Provider.OPENAI, "gpt-5-mini", input_tokens=1_000_000, output_tokens=0)
    assert cents == 25
    cents = estimate_cost_cents(Provider.OPENAI, "gpt-5-mini", input_tokens=0, output_tokens=1_000_000)
    assert cents == 200


def test_cost_is_zero_for_zero_usage() -> None:
    assert estimate_cost_cents(Provider.CLAUDE, "claude-sonnet-5", input_tokens=0, output_tokens=0) == 0


def test_unknown_model_raises_rather_than_silently_assuming_zero_cost() -> None:
    with pytest.raises(UnknownModelPricingError):
        estimate_cost_cents(
            Provider.OPENAI, "some-future-model-nobody-priced-yet", input_tokens=10, output_tokens=10
        )


def test_unknown_provider_for_a_known_model_name_also_raises() -> None:
    with pytest.raises(UnknownModelPricingError):
        estimate_cost_cents(Provider.GEMINI, "gpt-5-mini", input_tokens=10, output_tokens=10)


@pytest.mark.parametrize(
    ("char_count", "expected_tokens"),
    [
        (0, 1),  # never zero — a reservation of $0 would defeat the budget gate entirely
        (1, 1),
        (3, 1),
        (4, 2),  # rounds UP, never down — this number gates whether a call is allowed at all
        (6, 2),
        (300, 100),
    ],
)
def test_char_to_token_heuristic_rounds_up_and_never_returns_zero(
    char_count: int, expected_tokens: int
) -> None:
    assert estimate_input_tokens_from_chars(char_count) == expected_tokens
