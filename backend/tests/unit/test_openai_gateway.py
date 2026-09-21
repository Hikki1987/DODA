"""`doda.infrastructure.openai_gateway` against a real `openai.AsyncOpenAI`
client whose HTTP transport is replaced with `httpx2.MockTransport` — the
SDK's own streaming/error-handling code runs for real; only the network
call itself is faked. No real OpenAI API key or network access is used
or required (this environment's network policy blocks api.openai.com
entirely — see ADR-008). This is explicitly a MOCK test, not a real-API
integration test — see tests/integration/test_conversations_api.py for
what actually runs against real Postgres, and the eval harness
(backend/scripts/run_ai_eval_suite.py) for the one place a real key,
when present, is actually exercised.
"""

import json

import httpx2
import pytest

from doda.ai.errors import (
    ModelAuthenticationError,
    ModelProviderError,
    ModelRateLimitedError,
    ModelTimeoutError,
)
from doda.ai.types import ChatMode, ChatRole, ChatTurn, Completed, TextDelta, ToolCallReady, ToolSpec
from doda.infrastructure.openai_gateway import OpenAIGateway

FAKE_API_KEY = "sk-super-secret-test-key-must-never-leak"


def _sse_body(events: list[dict]) -> bytes:
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode()


def _gateway(handler) -> OpenAIGateway:
    gateway = OpenAIGateway(api_key=FAKE_API_KEY, timeout_seconds=5.0)
    # max_retries=0: the mock handler below returns the same deterministic
    # response every call, so the SDK's own built-in retry (which this
    # adapter otherwise relies on for pre-stream connection failures —
    # see the module docstring's retry-boundary note) would just sleep
    # through real backoff delays against a transport that can never
    # succeed. Irrelevant to what each test actually verifies.
    gateway._client = gateway._client.with_options(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), max_retries=0
    )
    return gateway


async def _collect(gateway: OpenAIGateway, **kwargs):
    kwargs.setdefault("model", "gpt-5-mini")
    kwargs.setdefault("mode", ChatMode.STANDARD)
    kwargs.setdefault("instructions", "")
    kwargs.setdefault("history", [ChatTurn(role=ChatRole.USER, content="salom")])
    kwargs.setdefault("tools", [])
    kwargs.setdefault("max_output_tokens", 256)
    events = []
    async for event in gateway.stream_chat(**kwargs):
        events.append(event)
    return events


async def test_text_streaming_and_completion() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = _sse_body(
            [
                {"type": "response.output_text.delta", "delta": "Salom", "sequence_number": 1},
                {"type": "response.output_text.delta", "delta": ", DODA!", "sequence_number": 2},
                {
                    "type": "response.completed",
                    "sequence_number": 3,
                    "response": {
                        "id": "resp_1",
                        "object": "response",
                        "created_at": 0,
                        "model": "gpt-5-mini",
                        "status": "completed",
                        "output": [],
                        "parallel_tool_calls": True,
                        "tool_choice": "auto",
                        "tools": [],
                        "usage": {
                            "input_tokens": 10,
                            "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                            "output_tokens": 5,
                            "output_tokens_details": {"reasoning_tokens": 0},
                            "total_tokens": 15,
                        },
                    },
                },
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
                {
                    "type": "response.output_item.added",
                    "sequence_number": 1,
                    "output_index": 0,
                    "item": {
                        "type": "function_call",
                        "id": "item_1",
                        "call_id": "call_abc",
                        "name": "list_my_open_tasks",
                        "arguments": "",
                    },
                },
                {
                    "type": "response.function_call_arguments.done",
                    "sequence_number": 2,
                    "output_index": 0,
                    "item_id": "item_1",
                    "arguments": '{"limit": 5}',
                },
                {
                    "type": "response.completed",
                    "sequence_number": 3,
                    "response": {
                        "id": "resp_2",
                        "object": "response",
                        "created_at": 0,
                        "model": "gpt-5-mini",
                        "status": "completed",
                        "output": [
                            {
                                "type": "function_call",
                                "id": "item_1",
                                "call_id": "call_abc",
                                "name": "list_my_open_tasks",
                                "arguments": '{"limit": 5}',
                            }
                        ],
                        "parallel_tool_calls": True,
                        "tool_choice": "auto",
                        "tools": [],
                        "usage": {
                            "input_tokens": 20,
                            "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                            "output_tokens": 8,
                            "output_tokens_details": {"reasoning_tokens": 0},
                            "total_tokens": 28,
                        },
                    },
                },
            ]
        )
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    gateway = _gateway(handler)
    events = await _collect(
        gateway, tools=[ToolSpec(name="list_my_open_tasks", description="...", parameters_schema={})]
    )

    calls = [e for e in events if isinstance(e, ToolCallReady)]
    assert len(calls) == 1
    assert calls[0].call.call_id == "call_abc"
    assert calls[0].call.name == "list_my_open_tasks"
    assert json.loads(calls[0].call.arguments_json) == {"limit": 5}
    completed = [e for e in events if isinstance(e, Completed)]
    assert completed[0].finish_reason == "tool_calls"


async def test_authentication_error_never_leaks_the_api_key() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert FAKE_API_KEY not in request.url.raw_path.decode()  # key must be in the header, not the URL
        return httpx2.Response(
            401,
            headers={"content-type": "application/json"},
            json={"error": {"message": "Incorrect API key provided", "type": "invalid_request_error"}},
        )

    gateway = _gateway(handler)
    with pytest.raises(ModelAuthenticationError) as exc_info:
        await _collect(gateway)

    assert FAKE_API_KEY not in str(exc_info.value)
    assert FAKE_API_KEY not in repr(exc_info.value)


async def test_rate_limit_error_is_translated_with_retry_after() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            429,
            headers={"content-type": "application/json", "retry-after": "7"},
            json={"error": {"message": "Rate limit exceeded", "type": "rate_limit_error"}},
        )

    gateway = _gateway(handler)
    with pytest.raises(ModelRateLimitedError) as exc_info:
        await _collect(gateway)

    assert exc_info.value.retry_after_seconds == 7.0
    assert FAKE_API_KEY not in str(exc_info.value)


async def test_timeout_is_translated_to_model_timeout_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.TimeoutException("simulated timeout")

    gateway = _gateway(handler)
    with pytest.raises(ModelTimeoutError):
        await _collect(gateway)


async def test_server_error_is_translated_without_leaking_raw_sdk_text() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            503,
            headers={"content-type": "application/json"},
            json={
                "error": {
                    "message": "The server had an error processing your request",
                    "type": "server_error",
                }
            },
        )

    gateway = _gateway(handler)
    with pytest.raises(ModelProviderError) as exc_info:
        await _collect(gateway)

    assert FAKE_API_KEY not in str(exc_info.value)
    assert exc_info.value.status_code == 503
