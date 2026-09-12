"""Per-(provider, model) pricing — used to both ESTIMATE cost before a
gateway call (`doda.application.ai_budget_service`, so a request can be
refused before any provider call is made) and to compute the ACTUAL cost
after a call from its real `GatewayUsage`.

**Honest sourcing note (ADR-008/ADR-009)**: every provider's own pricing
page is blocked by this environment's network egress policy — verified
2026-09-12 with `curl` (platform.openai.com, docs.anthropic.com,
ai.google.dev all return a proxy-level connect rejection; same class of
restriction already documented elsewhere in this codebase for
api.telegram.org, accounts.google.com, and render.com). The figures below
are a multi-source web-search consensus (independent pricing-aggregator
sites agreeing on the same numbers), NOT a primary-source confirmation.
Treat them as a reasoned starting point for budget estimation, not as
contractually exact — re-verify directly against each provider's own
dashboard before relying on this for real billing reconciliation.

Model ids themselves ARE primary-sourced, from each provider's own
Python SDK, installed fresh from PyPI 2026-09-12:
`openai.types.shared.chat_model.ChatModel` (openai 3.13.0),
`anthropic.types.model_param.ModelParam` (anthropic 1.5.0), and the
model-id strings shipped throughout `google.genai` (google-genai 2.23.0).
"""

import dataclasses

from doda.ai.types import Provider

CENTS_PER_DOLLAR = 100
TOKENS_PER_PRICING_UNIT = 1_000_000


@dataclasses.dataclass(frozen=True)
class ModelPricing:
    input_usd_per_million: float
    output_usd_per_million: float


# Only models doda.config.Settings.ai_model_* actually points at by
# default have an entry — add one here before configuring any
# ai_model_* setting to a new model id, or cost estimation for it will
# raise (see estimate_cost_cents) rather than silently guessing.
MODEL_PRICING: dict[Provider, dict[str, ModelPricing]] = {
    Provider.OPENAI: {
        "gpt-5-mini": ModelPricing(input_usd_per_million=0.25, output_usd_per_million=2.00),
        "gpt-5-nano": ModelPricing(input_usd_per_million=0.05, output_usd_per_million=0.40),
        "gpt-4.1-mini": ModelPricing(input_usd_per_million=0.40, output_usd_per_million=1.60),
    },
    Provider.CLAUDE: {
        # Anthropic's own permanent rate per multiple independent sources
        # (including a cloudzero.com summary explicitly describing it as
        # sourced from Anthropic's official platform docs) — see module
        # docstring for why that page itself couldn't be fetched directly.
        "claude-sonnet-5": ModelPricing(input_usd_per_million=2.00, output_usd_per_million=10.00),
    },
    Provider.GEMINI: {
        # Google AI Studio direct pricing; third-party resellers quote a
        # range as low as $0.125/$0.75 — this uses the higher, more
        # conservative figure for budget estimation (never underestimate
        # a cost that gates whether a call is allowed to happen).
        "gemini-3.1-flash-lite": ModelPricing(input_usd_per_million=0.25, output_usd_per_million=1.50),
    },
}


class UnknownModelPricingError(Exception):
    pass


def estimate_cost_cents(provider: Provider, model: str, *, input_tokens: int, output_tokens: int) -> int:
    pricing = MODEL_PRICING.get(provider, {}).get(model)
    if pricing is None:
        raise UnknownModelPricingError(
            f"no pricing entry for {provider.value}/{model!r} — add one to MODEL_PRICING before using it"
        )
    dollars = (input_tokens / TOKENS_PER_PRICING_UNIT) * pricing.input_usd_per_million + (
        output_tokens / TOKENS_PER_PRICING_UNIT
    ) * pricing.output_usd_per_million
    return round(dollars * CENTS_PER_DOLLAR)


def estimate_input_tokens_from_chars(char_count: int) -> int:
    """A rough, deliberately conservative heuristic (no tokenizer
    dependency for a pre-call budget check): ~3 characters per token
    rounds UP from the commonly-cited ~4-chars-per-token English average
    — Uzbek/Cyrillic text can run denser, so this errs toward reserving
    slightly more budget than a real tokenizer would report, never less,
    since this number gates whether a call is allowed to happen at all."""
    return max(1, -(-char_count // 3))
