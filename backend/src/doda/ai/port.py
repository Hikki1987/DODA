"""ADR-004/ADR-008/ADR-009's "model gateway" — the one seam a real AI/LLM
provider integration enters through. `doda.application.conversation_
service` talks only to this Protocol, never to a provider SDK directly
(6.2: "Web/Application qatlami to'g'ridan-to'g'ri tashqi providerga
ulanmaydi" — the AI layer is where that connection is allowed to exist,
nowhere else).

One adapter class per provider (`doda.infrastructure.openai_gateway.
OpenAIGateway`, `.gemini_gateway.GeminiGateway`, `.claude_gateway.
ClaudeGateway`) — each implements this same Protocol. `doda.ai.factory`
picks which instance to use for a given `Provider`; nothing above that
factory needs to know which adapter it got.

`NullModelGateway` is the fallback used whenever a provider has no
configured credential — every test environment and CI today for all
three, and any production deployment before a key is provided for one of
them. It never makes a network call and never reads the history or tools
it is given, so it cannot leak anything even if misused.
"""

import typing
from typing import Any

from doda.ai.types import ChatMode, ChatTurn, Completed, GatewayEvent, GatewayUsage, TextDelta, ToolSpec


@typing.runtime_checkable
class ModelGateway(typing.Protocol):
    """`stream_chat` is the only method a provider adapter must implement.
    It is an async generator: callers iterate `GatewayEvent`s as they
    arrive rather than waiting for one complete response, which is what
    makes FR-CONV-002's streaming possible.

    `model` is the specific model id within this adapter's own provider
    (e.g. "gpt-5-mini") — never validated against another provider's
    names. `mode` selects an output-length/cost tier orthogonal to model
    choice (`doda.config.Settings`'s ai_max_output_tokens_* /
    ai_deep_request_cost_ceiling_usd). `response_schema`, when given,
    asks for TRD 7.3's "qat'iy JSON schema" structured output instead of
    free text — `doda.ai.capabilities.assert_supports_structured_output`
    must be checked by the caller first; an adapter that cannot honor it
    must raise rather than silently ignore the schema."""

    def stream_chat(
        self,
        *,
        model: str,
        mode: ChatMode,
        instructions: str,
        history: list[ChatTurn],
        tools: list[ToolSpec],
        max_output_tokens: int,
        response_schema: dict[str, Any] | None = None,
    ) -> typing.AsyncIterator[GatewayEvent]: ...


_NULL_GATEWAY_REPLY_TEXT = (
    "AI javob provayderi hali tanlanmagan yoki sozlanmagan. Bu xabar "
    "saqlandi, lekin hech qanday tashqi modelga yuborilmadi."
)


class NullModelGateway:
    """FR-CONV-008's "safe degradation" when a provider has no
    configured credential: say so plainly in a single text event, then
    end the turn — never a network call, never a fabricated-looking
    answer. Every conversation gets the exact same reply for the exact
    same reason this session's scaffolding `NullAIPort` did."""

    async def stream_chat(
        self,
        *,
        model: str,
        mode: ChatMode,
        instructions: str,
        history: list[ChatTurn],
        tools: list[ToolSpec],
        max_output_tokens: int,
        response_schema: dict[str, Any] | None = None,
    ) -> typing.AsyncIterator[GatewayEvent]:
        del model, mode, instructions, history, tools, max_output_tokens, response_schema
        yield TextDelta(text=_NULL_GATEWAY_REPLY_TEXT)
        yield Completed(usage=GatewayUsage(input_tokens=0, output_tokens=0), finish_reason="stop")
