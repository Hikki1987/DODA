"""Unit tests for `doda.ai.capabilities` — no DB, no network. Every
provider this codebase configures supports tool calling and structured
output today, so the registry's raise paths are exercised with a
monkeypatched, deliberately-disabled entry rather than a real one — the
same "prove the check can actually fire" discipline as every concurrency
fix's revert-test-restore elsewhere in this codebase, applied to a static
check instead of a race.
"""

import pytest

from doda.ai import capabilities
from doda.ai.capabilities import (
    ModelCapabilities,
    UnsupportedModelCapabilityError,
    assert_supports_structured_output,
    assert_supports_tools,
    capabilities_for,
)
from doda.ai.types import Provider


@pytest.mark.parametrize("provider", list(Provider))
def test_every_configured_provider_has_a_capability_entry(provider: Provider) -> None:
    caps = capabilities_for(provider)
    assert caps.tool_calling is True
    assert caps.structured_output is True


@pytest.mark.parametrize("provider", list(Provider))
def test_no_tools_requested_never_raises_even_in_principle(provider: Provider) -> None:
    assert_supports_tools(provider, requested_tools=[])


def test_requesting_tools_against_a_model_that_cannot_call_them_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        capabilities._PROVIDER_CAPABILITIES, Provider.OPENAI, ModelCapabilities(tool_calling=False)
    )
    with pytest.raises(UnsupportedModelCapabilityError, match="tool calling"):
        assert_supports_tools(Provider.OPENAI, requested_tools=["list_my_open_tasks"])


def test_structured_output_against_a_model_that_cannot_emit_it_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        capabilities._PROVIDER_CAPABILITIES, Provider.GEMINI, ModelCapabilities(structured_output=False)
    )
    with pytest.raises(UnsupportedModelCapabilityError, match="structured output"):
        assert_supports_structured_output(Provider.GEMINI)
