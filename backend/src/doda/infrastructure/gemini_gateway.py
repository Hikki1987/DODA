"""Google Gemini adapter (ADR-009) — the only module in this codebase
allowed to know `google-genai`'s SDK shape. Uses
`client.aio.models.generate_content_stream(...)` — the SDK's own async
streaming entry point; there is no separate "Responses API"-equivalent
choice to make here the way OpenAI has Chat Completions vs Responses —
`generate_content`/`generate_content_stream` is the one current
content-generation surface (google-genai 2.23.0, verified 2026-09-12).

`automatic_function_calling` is explicitly DISABLED
(`AutomaticFunctionCallingConfig(disable=True)`) — the SDK can, by
default, auto-invoke Python callables passed as tools. DODA never lets
the AI layer execute anything itself (6.2: "AI qatlami authoritative
avtorizatsiya qarorini chiqarmaydi"); every tool call, however trivial,
must surface as a `ToolCallReady` event and go through `doda.
application.ai_tools`' own authz-aware dispatch.

Every error path raises only `doda.ai.errors.ModelGatewayError`
subtypes, using only `exc.code`/`exc.message` (google-genai's own
structured `APIError` fields — provider-reported, not a raw exception
dump) or `type(exc).__name__` — never the request object, which carries
the API key as a query parameter for this provider (`?key=...`) rather
than a header. See `tests/unit/test_gemini_gateway.py` for the
regression test proving the key never appears in a raised error.
"""

import json
import typing
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from doda.ai.errors import ModelProviderError, ModelRateLimitedError, ModelTimeoutError
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

_FUNCTION_RESULT_KEY = "result"


def _to_gemini_contents(history: list[ChatTurn]) -> list[genai_types.Content]:
    contents: list[genai_types.Content] = []
    for turn in history:
        if turn.role is ChatRole.TOOL:
            contents.append(
                genai_types.Content(
                    role="user",
                    parts=[
                        genai_types.Part.from_function_response(
                            name=turn.tool_call_id or "", response={_FUNCTION_RESULT_KEY: turn.content}
                        )
                    ],
                )
            )
        elif turn.tool_calls:
            contents.append(
                genai_types.Content(
                    role="model",
                    parts=[
                        genai_types.Part.from_function_call(
                            name=call.name, args=json.loads(call.arguments_json)
                        )
                        for call in turn.tool_calls
                    ],
                )
            )
        else:
            role = "user" if turn.role is ChatRole.USER else "model"
            contents.append(
                genai_types.Content(role=role, parts=[genai_types.Part.from_text(text=turn.content)])
            )
    return contents


def _to_gemini_tools(tools: list[ToolSpec]) -> list[genai_types.Tool]:
    return [
        genai_types.Tool(
            function_declarations=[
                genai_types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters_json_schema=tool.parameters_schema,
                )
            ]
        )
        for tool in tools
    ]


def _translate_error(exc: Exception) -> Exception:
    if isinstance(exc, httpx.TimeoutException):
        return ModelTimeoutError("Gemini did not respond within the configured timeout")
    if isinstance(exc, genai_errors.APIError):
        if exc.code == 429:
            return ModelRateLimitedError(f"Gemini rate-limited this request: {exc.message or ''}".strip())
        return ModelProviderError(
            f"Gemini returned an error: {exc.message or type(exc).__name__}", status_code=exc.code
        )
    return ModelProviderError(f"Gemini request failed: {type(exc).__name__}")


class GeminiGateway:
    """Holds one `genai.Client`, constructed once with the configured API
    key — see module docstring for why `automatic_function_calling` is
    always disabled and why errors never carry the raw request."""

    def __init__(
        self, *, api_key: str, timeout_seconds: float, http_client: httpx.AsyncClient | None = None
    ) -> None:
        # `http_client` is a testability seam only (tests/unit/
        # test_gemini_gateway.py injects an httpx.MockTransport-backed
        # client here) — production construction (doda.ai.factory) never
        # passes it, so the real timeout-derived HttpOptions always wins.
        http_options = (
            genai_types.HttpOptions(httpx_async_client=http_client)
            if http_client is not None
            else genai_types.HttpOptions(timeout=round(timeout_seconds * 1000))
        )
        self._client = genai.Client(api_key=api_key, http_options=http_options)

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
        config_kwargs: dict[str, Any] = {
            "system_instruction": instructions or None,
            "max_output_tokens": max_output_tokens,
            "automatic_function_calling": genai_types.AutomaticFunctionCallingConfig(disable=True),
        }
        if tools:
            config_kwargs["tools"] = _to_gemini_tools(tools)
        if response_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_json_schema"] = response_schema
        config = genai_types.GenerateContentConfig(**config_kwargs)

        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=model, contents=_to_gemini_contents(history), config=config
            )
        except Exception as exc:
            raise _translate_error(exc) from None

        finish_reason = "stop"
        usage = GatewayUsage(input_tokens=0, output_tokens=0)
        saw_tool_call = False
        structured_text = ""
        try:
            async for chunk in stream:
                for index, call in enumerate(chunk.function_calls or []):
                    saw_tool_call = True
                    # Gemini does not always assign FunctionCall.id — when
                    # absent, synthesize one scoped to this chunk/index so
                    # concurrent calls in the same turn can never collide;
                    # unlike OpenAI's call_id, this is NOT a stable
                    # identifier a caller could use to deduplicate a
                    # retried gateway call (a known, documented gap —
                    # module docstring).
                    yield ToolCallReady(
                        call=ToolCallRequest(
                            call_id=call.id or f"gemini-call-{call.name}-{index}",
                            name=call.name or "",
                            arguments_json=json.dumps(call.args or {}),
                        )
                    )
                text = chunk.text
                if text:
                    if response_schema is not None:
                        structured_text += text
                    else:
                        yield TextDelta(text=text)
                if chunk.usage_metadata is not None:
                    usage = GatewayUsage(
                        input_tokens=chunk.usage_metadata.prompt_token_count or 0,
                        output_tokens=chunk.usage_metadata.candidates_token_count or 0,
                        cached_input_tokens=chunk.usage_metadata.cached_content_token_count or 0,
                    )
                for candidate in chunk.candidates or []:
                    if candidate.finish_reason is not None:
                        reason = str(candidate.finish_reason)
                        if "MAX_TOKENS" in reason:
                            finish_reason = "length"
        except Exception as exc:
            raise _translate_error(exc) from None

        if response_schema is not None and structured_text and not saw_tool_call:
            yield StructuredOutputReady(data=json.loads(structured_text))

        yield Completed(usage=usage, finish_reason=("tool_calls" if saw_tool_call else finish_reason))
