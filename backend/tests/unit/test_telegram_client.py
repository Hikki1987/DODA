"""Unit tests for the Telegram Bot API client's request/response handling.

These use httpx.MockTransport — a stand-in for the network, not a real
call to Telegram's API. That is a deliberate, standard technique for
testing an HTTP client's own logic (request shape, response parsing,
error handling) in isolation; it is not a claim that a real message was
sent. Whether this client actually works against the real Telegram
service has not been verified anywhere in this codebase — no real bot
token or chat is available in this environment. See
infra_telegram_relay.py's own docstring and
tests/integration/test_telegram_relay.py for what IS verified end-to-end
(everything except this one external HTTP leg).
"""

import httpx
import pytest

from doda.infrastructure.telegram_client import TelegramSendError, send_message


async def test_successful_send_returns_the_message_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/bot123:ABC/sendMessage"
        assert request.headers["content-type"] == "application/json"
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await send_message(client, bot_token="123:ABC", chat_id="555", text="hello")
    assert result.message_id == 42


async def test_request_body_carries_chat_id_and_text() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await send_message(client, bot_token="tok", chat_id="chat-1", text="the message")
    assert captured == {"chat_id": "chat-1", "text": "the message"}


async def test_api_level_failure_raises_telegram_send_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "chat not found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(TelegramSendError, match="chat not found"):
        await send_message(client, bot_token="tok", chat_id="missing", text="hi")


async def test_network_error_raises_telegram_send_error_without_leaking_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connection refused to {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(TelegramSendError) as exc_info:
        await send_message(client, bot_token="super-secret-token", chat_id="1", text="hi")

    # The whole point of the module's error handling: the bot token lives
    # in the URL, so a careless `str(original_exception)` would leak it
    # into logs. Assert it never appears in the raised error's message.
    assert "super-secret-token" not in str(exc_info.value)


async def test_malformed_json_response_raises_telegram_send_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(TelegramSendError):
        await send_message(client, bot_token="tok", chat_id="1", text="hi")
