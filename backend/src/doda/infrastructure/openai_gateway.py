"""OpenAI adapter (ADR-008) — the only module in this codebase allowed to
know OpenAI's SDK shape. Implements `doda.ai.port.ModelGateway` via the
Responses API (`client.responses.create(stream=True, ...)`), chosen over
Chat Completions per ADR-008's sourcing note: OpenAI's own migration
guide recommends Responses API for new projects, it is stateful-capable
(`previous_response_id` — not used here; this codebase keeps its own
history in `doda.domain.conversation.models.Message` instead, per the
explicit instruction that DODA's own storage stays authoritative), and
its streaming is semantic typed events rather than raw text deltas,
which is what makes tool-call argument accumulation in this module
tractable.

`store=False` is always passed — NOT because that is Zero Data
Retention (the `openai` SDK's own docstring on `responses.create`
explicitly distinguishes `store=False` from "an organization is
enrolled in the zero data retention program"; see ADR-008) but because
DODA does not want OpenAI retaining a second copy of conversation
history it already keeps itself.

Every error path below raises only `doda.ai.errors.ModelGatewayError`
subtypes, and extracts only structured, safe fields from the SDK's own
exceptions (`type(exc).__name__`, `exc.status_code`, a provider-reported
`message` from a structured error event/body) — never a bare `str(exc)`
or the request object, which could otherwise carry the API key via its
Authorization header. See `tests/unit/test_openai_gateway.py` for the
regression test proving the key never appears in a raised error.
"""

import json
import typing
from typing import Any

import openai

from doda.ai.errors import (
    ModelAuthenticationError,
    ModelProviderError,
    ModelRateLimitedError,
    ModelTimeoutError,
)
from doda.ai.types import (
    ChatMode,
    ChatRole,
    ChatTurn,
    Completed,
    GatewayEvent,
    GatewayUsage,
    StructuredOutputReady,
    TextDelta,
    ToolCallReady,
    ToolCallRequest,
    ToolSpec,
)

_STRUCTURED_OUTPUT_SCHEMA_NAME = "doda_structured_output"


def _to_openai_input(history: list[ChatTurn]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for turn in history:
        if turn.role is ChatRole.TOOL:
            items.append(
                {"type": "function_call_output", "call_id": turn.tool_call_id, "output": turn.content}
            )
        elif turn.tool_calls:
            for call in turn.tool_calls:
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call.call_id,
                        "name": call.name,
                        "arguments": call.arguments_json,
                    }
                )
        else:
            role = "user" if turn.role is ChatRole.USER else "assistant"
            items.append({"role": role, "content": turn.content})
    return items


def _to_openai_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters_schema,
            "strict": False,
        }
        for tool in tools
    ]


def _translate_error(exc: Exception) -> Exception:
    """Maps an openai SDK exception to a doda.ai.errors type, using only
    safe, structured fields — see module docstring."""
    if isinstance(exc, openai.AuthenticationError):
        return ModelAuthenticationError("OpenAI rejected the configured API key")
    if isinstance(exc, openai.RateLimitError):
        retry_after = None
        headers = getattr(getattr(exc, "response", None), "headers", None)
        if headers is not None:
            raw = headers.get("retry-after")
            if raw is not None:
                try:
                    retry_after = float(raw)
                except ValueError:
                    retry_after = None
        return ModelRateLimitedError("OpenAI rate-limited this request", retry_after_seconds=retry_after)
    if isinstance(exc, openai.APITimeoutError):
        return ModelTimeoutError("OpenAI did not respond within the configured timeout")
    if isinstance(exc, openai.APIStatusError):
        return ModelProviderError(
            f"OpenAI returned an error: {exc.type or type(exc).__name__}", status_code=exc.status_code
        )
    return ModelProviderError(f"OpenAI request failed: {type(exc).__name__}")


class OpenAIGateway:
    """Holds one `openai.AsyncOpenAI` client, constructed once with the
    configured API key and timeout (`doda.ai.factory`). Never logs the
    key; never accepts it as a per-call argument (so no call site can
    accidentally forward someone else's key)."""

    def __init__(self, *, api_key: str, timeout_seconds: float) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)

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
        del mode  # only affects max_output_tokens, already resolved by the caller
        create_kwargs: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": _to_openai_input(history),
            "max_output_tokens": max_output_tokens,
            "stream": True,
            "store": False,
        }
        if tools:
            create_kwargs["tools"] = _to_openai_tools(tools)
        if response_schema is not None:
            create_kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": _STRUCTURED_OUTPUT_SCHEMA_NAME,
                    "schema": response_schema,
                    "strict": True,
                }
            }

        try:
            stream = await self._client.responses.create(**create_kwargs)
        except Exception as exc:
            raise _translate_error(exc) from None

        item_call_info: dict[str, tuple[str, str]] = {}  # item.id -> (call_id, name)
        try:
            async for event in stream:
                event_type = getattr(event, "type", None)
                if event_type == "response.output_text.delta":
                    yield TextDelta(text=event.delta)
                elif event_type == "response.output_item.added":
                    item = event.item
                    if getattr(item, "type", None) == "function_call" and item.id is not None:
                        item_call_info[item.id] = (item.call_id, item.name)
                elif event_type == "response.function_call_arguments.done":
                    call_info = item_call_info.get(event.item_id)
                    if call_info is not None:
                        call_id, name = call_info
                        yield ToolCallReady(
                            call=ToolCallRequest(call_id=call_id, name=name, arguments_json=event.arguments)
                        )
                elif event_type == "error":
                    raise ModelProviderError(f"OpenAI stream error: {event.message}")
                elif event_type == "response.completed":
                    response = event.response
                    usage = response.usage
                    has_tool_calls = any(
                        getattr(item, "type", None) == "function_call" for item in response.output
                    )
                    if response_schema is not None and not has_tool_calls:
                        text = "".join(
                            part.text
                            for item in response.output
                            if getattr(item, "type", None) == "message"
                            for part in item.content
                            if getattr(part, "type", None) == "output_text"
                        )
                        if text:
                            yield StructuredOutputReady(data=json.loads(text))
                    finish_reason = (
                        "tool_calls"
                        if has_tool_calls
                        else ("length" if response.status == "incomplete" else "stop")
                    )
                    yield Completed(
                        usage=GatewayUsage(
                            input_tokens=usage.input_tokens if usage else 0,
                            output_tokens=usage.output_tokens if usage else 0,
                            cached_input_tokens=usage.input_tokens_details.cached_tokens if usage else 0,
                        ),
                        finish_reason=finish_reason,
                    )
        except Exception as exc:
            if isinstance(exc, ModelProviderError):
                raise
            raise _translate_error(exc) from None
