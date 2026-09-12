"""Anthropic Claude adapter (ADR-009) — the only module in this codebase
allowed to know `anthropic`'s SDK shape. Uses the Messages API
(`client.messages.create(stream=True, ...)`) — the one content-
generation surface the instructions ask to verify for Claude; there is
no separate "Responses API"-equivalent choice here (`anthropic` 1.5.0,
verified 2026-09-12).

**Structured output is EMULATED, not native** (see
`doda.ai.capabilities`'s module docstring for why): the Messages API has
no `response_format`-shaped parameter as of this SDK version. When
`response_schema` is given, this adapter defines one synthetic tool
(`_STRUCTURED_OUTPUT_TOOL_NAME`) whose `input_schema` IS the requested
schema, forces it with `tool_choice={"type": "tool", "name": ...}`, and
converts the resulting `tool_use` block's `input` into a
`StructuredOutputReady` event instead of a `ToolCallReady` — the rest of
the codebase (`doda.application.ai_tools`) never sees this synthetic
tool or dispatches it.

Every error path raises only `doda.ai.errors.ModelGatewayError`
subtypes, using only `type(exc).__name__`/`exc.status_code`/a
provider-reported `message` — never a bare `str(exc)` or the request
object, which could carry the API key via its own Authorization-style
header. See `tests/unit/test_claude_gateway.py` for the regression test
proving the key never appears in a raised error.
"""

import json
import typing
from typing import Any

import anthropic

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

_STRUCTURED_OUTPUT_TOOL_NAME = "__doda_structured_output__"


def _to_claude_messages(history: list[ChatTurn]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for turn in history:
        if turn.role is ChatRole.TOOL:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": turn.tool_call_id, "content": turn.content}
                    ],
                }
            )
        elif turn.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": call.call_id,
                            "name": call.name,
                            "input": json.loads(call.arguments_json),
                        }
                        for call in turn.tool_calls
                    ],
                }
            )
        else:
            role = "user" if turn.role is ChatRole.USER else "assistant"
            messages.append({"role": role, "content": turn.content})
    return messages


def _to_claude_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {"name": tool.name, "description": tool.description, "input_schema": tool.parameters_schema}
        for tool in tools
    ]


def _translate_error(exc: Exception) -> Exception:
    if isinstance(exc, anthropic.AuthenticationError):
        return ModelAuthenticationError("Claude rejected the configured API key")
    if isinstance(exc, anthropic.RateLimitError):
        retry_after = None
        headers = getattr(getattr(exc, "response", None), "headers", None)
        if headers is not None:
            raw = headers.get("retry-after")
            if raw is not None:
                try:
                    retry_after = float(raw)
                except ValueError:
                    retry_after = None
        return ModelRateLimitedError("Claude rate-limited this request", retry_after_seconds=retry_after)
    if isinstance(exc, anthropic.APITimeoutError):
        return ModelTimeoutError("Claude did not respond within the configured timeout")
    if isinstance(exc, anthropic.APIStatusError):
        return ModelProviderError(
            f"Claude returned an error: {type(exc).__name__}", status_code=exc.status_code
        )
    return ModelProviderError(f"Claude request failed: {type(exc).__name__}")


class ClaudeGateway:
    """Holds one `anthropic.AsyncAnthropic` client, constructed once with
    the configured API key and timeout (`doda.ai.factory`)."""

    def __init__(self, *, api_key: str, timeout_seconds: float) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_seconds)

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
        del mode
        create_kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_output_tokens,
            "messages": _to_claude_messages(history),
            "stream": True,
        }
        if instructions:
            create_kwargs["system"] = instructions

        claude_tools = _to_claude_tools(tools)
        if response_schema is not None:
            claude_tools.append(
                {
                    "name": _STRUCTURED_OUTPUT_TOOL_NAME,
                    "description": "Return the final answer as structured data matching the required schema.",
                    "input_schema": response_schema,
                }
            )
            create_kwargs["tool_choice"] = {"type": "tool", "name": _STRUCTURED_OUTPUT_TOOL_NAME}
        if claude_tools:
            create_kwargs["tools"] = claude_tools

        try:
            stream = await self._client.messages.create(**create_kwargs)
        except Exception as exc:
            raise _translate_error(exc) from None

        block_info: dict[int, tuple[str, str]] = {}  # index -> (type, id/name marker)
        tool_json_accumulator: dict[int, str] = {}
        usage = GatewayUsage(input_tokens=0, output_tokens=0)
        stop_reason: str | None = None
        try:
            async for event in stream:
                event_type = getattr(event, "type", None)
                if event_type == "message_start":
                    usage = GatewayUsage(
                        input_tokens=event.message.usage.input_tokens,
                        output_tokens=0,
                        cached_input_tokens=event.message.usage.cache_read_input_tokens or 0,
                    )
                elif event_type == "content_block_start":
                    block = event.content_block
                    if getattr(block, "type", None) == "tool_use":
                        block_info[event.index] = (block.id, block.name)
                        tool_json_accumulator[event.index] = ""
                elif event_type == "content_block_delta":
                    delta = event.delta
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "text_delta":
                        yield TextDelta(text=delta.text)
                    elif delta_type == "input_json_delta":
                        tool_json_accumulator[event.index] = (
                            tool_json_accumulator.get(event.index, "") + delta.partial_json
                        )
                elif event_type == "content_block_stop":
                    if event.index in block_info:
                        call_id, name = block_info[event.index]
                        arguments_json = tool_json_accumulator.get(event.index, "") or "{}"
                        if name == _STRUCTURED_OUTPUT_TOOL_NAME:
                            yield StructuredOutputReady(data=json.loads(arguments_json))
                        else:
                            yield ToolCallReady(
                                call=ToolCallRequest(
                                    call_id=call_id, name=name, arguments_json=arguments_json
                                )
                            )
                elif event_type == "message_delta":
                    usage = GatewayUsage(
                        input_tokens=usage.input_tokens,
                        output_tokens=event.usage.output_tokens,
                        cached_input_tokens=usage.cached_input_tokens,
                    )
                    if event.delta.stop_reason is not None:
                        stop_reason = str(event.delta.stop_reason)
        except Exception as exc:
            raise _translate_error(exc) from None

        finish_reason = "stop"
        if stop_reason == "tool_use":
            finish_reason = "tool_calls"
        elif stop_reason == "max_tokens":
            finish_reason = "length"
        yield Completed(usage=usage, finish_reason=finish_reason)
