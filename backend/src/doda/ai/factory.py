"""Picks which `ModelGateway` implementation backs a given `Provider` —
the one place that knows "no credential configured means
`NullModelGateway`, not a crash and not silently falling back to a
DIFFERENT provider" (the explicit instruction: a user's chosen provider
failing must never be silently swapped for another one).

Gateways are constructed once per process (one real HTTP client each)
and cached — `doda.main` calls `get_gateway` via a FastAPI dependency,
never constructs an adapter directly.
"""

from functools import lru_cache

from doda.ai.port import ModelGateway, NullModelGateway
from doda.ai.types import Provider
from doda.config import Settings, get_settings


@lru_cache
def _openai_gateway(api_key: str, timeout_seconds: float) -> ModelGateway:
    from doda.infrastructure.openai_gateway import OpenAIGateway

    return OpenAIGateway(api_key=api_key, timeout_seconds=timeout_seconds)


@lru_cache
def _gemini_gateway(api_key: str, timeout_seconds: float) -> ModelGateway:
    from doda.infrastructure.gemini_gateway import GeminiGateway

    return GeminiGateway(api_key=api_key, timeout_seconds=timeout_seconds)


@lru_cache
def _claude_gateway(api_key: str, timeout_seconds: float) -> ModelGateway:
    from doda.infrastructure.claude_gateway import ClaudeGateway

    return ClaudeGateway(api_key=api_key, timeout_seconds=timeout_seconds)


_NULL_GATEWAY = NullModelGateway()


def get_gateway(provider: Provider, settings: Settings | None = None) -> ModelGateway:
    settings = settings or get_settings()
    timeout = settings.ai_request_timeout_seconds

    if provider is Provider.OPENAI:
        key = settings.openai_api_key
        return _openai_gateway(key.get_secret_value(), timeout) if key is not None else _NULL_GATEWAY
    if provider is Provider.GEMINI:
        key = settings.gemini_api_key
        return _gemini_gateway(key.get_secret_value(), timeout) if key is not None else _NULL_GATEWAY
    if provider is Provider.CLAUDE:
        key = settings.claude_api_key
        return _claude_gateway(key.get_secret_value(), timeout) if key is not None else _NULL_GATEWAY
    raise AssertionError(f"unhandled provider: {provider}")  # pragma: no cover — Provider is exhaustive above


def is_provider_configured(provider: Provider, settings: Settings | None = None) -> bool:
    """Whether a real credential exists for `provider` — distinct from
    whether it is administratively ENABLED for a given customer (that is
    `doda.application.ai_provider_settings_service`'s concern, one layer
    up): this only answers "would get_gateway return a real adapter"."""
    settings = settings or get_settings()
    return {
        Provider.OPENAI: settings.openai_api_key,
        Provider.GEMINI: settings.gemini_api_key,
        Provider.CLAUDE: settings.claude_api_key,
    }[provider] is not None
