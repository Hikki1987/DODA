"""Unit tests for `doda.ai.factory` — no DB, no network. Constructing a
real adapter only builds an SDK client object; none of the three SDKs
make a network call at construction time, so these tests freely build
real `OpenAIGateway`/`GeminiGateway`/`ClaudeGateway` instances to prove
`get_gateway` picks the right class, without ever sending a request.
"""

from pydantic import SecretStr

from doda.ai.factory import get_gateway, is_provider_configured
from doda.ai.port import NullModelGateway
from doda.ai.types import Provider
from doda.config import Settings
from doda.infrastructure.claude_gateway import ClaudeGateway
from doda.infrastructure.gemini_gateway import GeminiGateway
from doda.infrastructure.openai_gateway import OpenAIGateway

_NO_KEYS = Settings(openai_api_key=None, gemini_api_key=None, claude_api_key=None)
_ALL_KEYS = Settings(
    openai_api_key=SecretStr("sk-test-openai"),
    gemini_api_key=SecretStr("test-gemini-key"),
    claude_api_key=SecretStr("sk-ant-test-claude"),
)


def test_an_unconfigured_provider_falls_back_to_the_null_gateway_never_a_different_provider() -> None:
    for provider in Provider:
        assert isinstance(get_gateway(provider, _NO_KEYS), NullModelGateway)
        assert is_provider_configured(provider, _NO_KEYS) is False


def test_a_configured_provider_returns_its_own_real_adapter_class() -> None:
    assert isinstance(get_gateway(Provider.OPENAI, _ALL_KEYS), OpenAIGateway)
    assert isinstance(get_gateway(Provider.GEMINI, _ALL_KEYS), GeminiGateway)
    assert isinstance(get_gateway(Provider.CLAUDE, _ALL_KEYS), ClaudeGateway)
    for provider in Provider:
        assert is_provider_configured(provider, _ALL_KEYS) is True


def test_configuring_one_provider_never_substitutes_it_for_a_different_unconfigured_one() -> None:
    """The explicit instruction: a user's chosen provider failing (here,
    simply not being configured) must never be silently swapped for
    another provider — only OpenAI has a key, Gemini/Claude still get
    their own NullModelGateway, never OpenAI's adapter."""
    only_openai = Settings(
        openai_api_key=SecretStr("sk-test-openai"), gemini_api_key=None, claude_api_key=None
    )
    assert isinstance(get_gateway(Provider.OPENAI, only_openai), OpenAIGateway)
    assert isinstance(get_gateway(Provider.GEMINI, only_openai), NullModelGateway)
    assert isinstance(get_gateway(Provider.CLAUDE, only_openai), NullModelGateway)
