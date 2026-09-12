"""`doda.infrastructure.claude_gateway` against a real `anthropic.
AsyncAnthropic` client whose HTTP transport is replaced with
`httpx2.MockTransport` (anthropic, like openai, moved to `httpx2` — see
the adapter's own module docstring) — the SDK's own SSE
decoding/streaming-event code runs for real; only the network call
itself is faked. No real Claude API key or network access is used or
required (docs.anthropic.com/api.anthropic.com are blocked by this
environment's network policy — see ADR-009). Explicitly a MOCK test —
see tests/integration/test_conversations_api.py and the eval harness for
what exercises a real key, when one is present.

Unlike OpenAI's Responses API (which discriminates purely on the JSON
body's own "type" field), Anthropic's SSE decoder keys off the explicit
`event:` line — confirmed by reading `anthropic/_streaming.py` directly
— so every mock event below sets both `event:` and `data:`.
"""

import json

import httpx2
import pytest

from doda.ai.errors import (
    ModelAuthenticationError,
    ModelProviderError,
    ModelRateLimitedError,
)
from doda.ai.types import ChatMode, ChatRole, ChatTurn, Completed, TextDelta, ToolCallReady, ToolSpec
from doda.infrastructure.claude_gateway import ClaudeGateway

FAKE_API_KEY = "sk-ant-super-secret-test-key-must-never-leak"


def _sse_body(events: list[dict]) -> bytes:
    return "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events).encode()


def _gateway(handler) -> ClaudeGateway:
    gateway = ClaudeGateway(api_key=FAKE_API_KEY, timeout_seconds=5.0)
    gateway._client = gateway._client.with_options(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), max_retries=0
    )
    return gateway


async def _collect(gateway: ClaudeGateway, **kwargs):
    kwargs.setdefault("model", "claude-sonnet-5")
    kwargs.setdefault("mode", ChatMode.STANDARD)
    kwargs.setdefault("instructions", "")
    kwargs.setdefault("history", [ChatTurn(role=ChatRole.USER, content="salom")])
    kwargs.setdefault("tools", [])
    kwargs.setdefault("max_output_tokens", 256)
    events = []
    async for event in gateway.stream_chat(**kwargs):
        events.append(event)
    return events


def _message_start(input_tokens: int = 10) -> dict:
    return {
        "type": "message_start",
        "message": {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": input_tokens, "output_tokens": 0},
        },
    }


async def test_text_streaming_and_completion() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = _sse_body(
            [
                _message_start(),
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Salom"},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": ", DODA!"},
                },
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 5},
                },
                {"type": "message_stop"},
            ]
        )
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    gateway = _gateway(handler)
    events = await _collect(gateway)

    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert text == "Salom, DODA!"
    completed = [e for e in events if isinstance(e, Completed)]
    assert len(completed) == 1
    assert completed[0].finish_reason == "stop"
    assert completed[0].usage.input_tokens == 10
    assert completed[0].usage.output_tokens == 5


async def test_tool_call_is_surfaced_with_full_arguments() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = _sse_body(
            [
                _message_start(input_tokens=20),
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "list_my_open_tasks",
                        "input": {},
                    },
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": '{"limit":'},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": " 5}"},
                },
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                    "usage": {"output_tokens": 8},
                },
                {"type": "message_stop"},
            ]
        )
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    gateway = _gateway(handler)
    events = await _collect(
        gateway, tools=[ToolSpec(name="list_my_open_tasks", description="...", parameters_schema={})]
    )

    calls = [e for e in events if isinstance(e, ToolCallReady)]
    assert len(calls) == 1
    assert calls[0].call.call_id == "toolu_1"
    assert calls[0].call.name == "list_my_open_tasks"
    assert json.loads(calls[0].call.arguments_json) == {"limit": 5}
    completed = [e for e in events if isinstance(e, Completed)]
    assert completed[0].finish_reason == "tool_calls"


async def test_authentication_error_never_leaks_the_api_key() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            401,
            headers={"content-type": "application/json"},
            json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}},
        )

    gateway = _gateway(handler)
    with pytest.raises(ModelAuthenticationError) as exc_info:
        await _collect(gateway)

    assert FAKE_API_KEY not in str(exc_info.value)


async def test_rate_limit_error_is_translated_with_retry_after() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            429,
            headers={"content-type": "application/json", "retry-after": "9"},
            json={"type": "error", "error": {"type": "rate_limit_error", "message": "rate limited"}},
        )

    gateway = _gateway(handler)
    with pytest.raises(ModelRateLimitedError) as exc_info:
        await _collect(gateway)

    assert exc_info.value.retry_after_seconds == 9.0
    assert FAKE_API_KEY not in str(exc_info.value)


async def test_server_error_is_translated_without_leaking_raw_sdk_text() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            529,
            headers={"content-type": "application/json"},
            json={"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
        )

    gateway = _gateway(handler)
    with pytest.raises(ModelProviderError) as exc_info:
        await _collect(gateway)

    assert FAKE_API_KEY not in str(exc_info.value)
