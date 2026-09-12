"""Explicit per-(provider, model) capability declarations (TRD 7.1:
"modelning mavjud imkoniyatlari tekshirilsin; qo'llamaydigan funksiyasini
ishlaydigan qilib ko'rsatma" — and the multi-provider instruction "mos
kelmaydigan boshqaruvlar interfeysda o'chirilsin yoki sababi
ko'rsatilsin... qo'llab-quvvatlanmaydigan parametrni yashirincha tashlab
yuborma").

Streaming and basic function/tool calling are supported by every model
this codebase configures by default today — verified against each
provider's own Python SDK (see ADR-008/ADR-009 for package versions and
the verification date): `openai` 3.13.0 (FunctionToolParam, streaming
events), `google-genai` 2.23.0 (`generate_content_stream`, function
declarations), `anthropic` 1.5.0 (Messages API streaming, `tool_use`
content blocks).

Native provider-enforced JSON-schema structured output is NOT uniform —
OpenAI (Responses API `text.format`) and Gemini (`response_schema`
generation config) support it directly; Claude's Messages API has no
equivalent as of `anthropic` 1.5.0 (confirmed by the absence of any
`response_format`-shaped parameter on `AsyncMessages.create` in that
package), so `doda.infrastructure.claude_gateway` emulates it via a
forced single tool call whose input schema IS the requested schema — a
real, working technique, but a provider-specific workaround rather than
a native capability, which is exactly why this registry exists: the rest
of the codebase asks `supports_structured_output(provider, model)` and
gets a real answer, not a guess baked into call-site logic.
"""

import dataclasses

from doda.ai.types import Provider


class UnsupportedModelCapabilityError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class ModelCapabilities:
    streaming: bool = True
    tool_calling: bool = True
    structured_output: bool = True
    vision_input: bool = False


# Keyed by provider only, not provider+model — every model this codebase
# currently defaults to (doda.config.Settings.ai_model_openai/gemini/
# claude) shares the same capability profile within its provider. Add a
# model-specific override only once a real, narrower model is actually
# configured (e.g. a vision-only or text-only variant) — speculative
# per-model rows would be exactly the unused machinery CLAUDE.md's
# "aloqasiz kodni o'zgartirma" discipline argues against.
_PROVIDER_CAPABILITIES: dict[Provider, ModelCapabilities] = {
    Provider.OPENAI: ModelCapabilities(structured_output=True),
    Provider.GEMINI: ModelCapabilities(structured_output=True),
    Provider.CLAUDE: ModelCapabilities(
        structured_output=True
    ),  # via forced-tool emulation, see module docstring
}


def capabilities_for(provider: Provider) -> ModelCapabilities:
    return _PROVIDER_CAPABILITIES[provider]


def assert_supports_tools(provider: Provider, *, requested_tools: list[str]) -> None:
    if requested_tools and not capabilities_for(provider).tool_calling:
        raise UnsupportedModelCapabilityError(f"{provider.value} does not support tool calling")


def assert_supports_structured_output(provider: Provider) -> None:
    if not capabilities_for(provider).structured_output:
        raise UnsupportedModelCapabilityError(f"{provider.value} does not support structured output")
