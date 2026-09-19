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

from doda.infrastructure.telegram_client import TelegramSendError, TelegramTransientError, send_message


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


# FR-ACT-005 (Must): "Provider outage simulyatsiyasida ma'lumot yo'qolmaydi" —
# telegram_relay.py retries TelegramTransientError specifically, so the
# client must actually distinguish it from a definitive, non-retryable
# rejection. UC-004's own mandated negative scenario — "provider timeout
# bergan lekin xat aslida yuborilgan" (the provider timed out, but the
# message was actually sent) — is why only failures KNOWN to have
# happened before Telegram could have queued anything are transient; a
# read timeout or a 5xx is genuinely ambiguous and must NOT be retried.


async def test_a_connect_error_is_a_transient_error() -> None:
    """The connection never reached Telegram at all — safe to retry."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(TelegramTransientError):
        await send_message(client, bot_token="tok", chat_id="1", text="hi")


async def test_429_response_is_a_transient_error() -> None:
    """Telegram explicitly rejected the request before queuing it for
    delivery — safe to retry."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"ok": False, "description": "Too Many Requests"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(TelegramTransientError):
        await send_message(client, bot_token="tok", chat_id="1", text="hi")


async def test_a_read_timeout_is_not_a_transient_error() -> None:
    """UC-004's own mandated negative scenario, verbatim: 'provider
    timeout bergan lekin xat aslida yuborilgan'. A read timeout means the
    request WAS sent — Telegram may have already processed it — so this
    must NOT be retried (it has no request-level idempotency key to make
    a retry safe): the base, non-retryable TelegramSendError, not
    TelegramTransientError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out waiting for a response")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(TelegramSendError) as exc_info:
        await send_message(client, bot_token="tok", chat_id="1", text="hi")

    assert not isinstance(exc_info.value, TelegramTransientError)


async def test_a_5xx_response_is_not_a_transient_error() -> None:
    """Same reasoning as a read timeout: Telegram's own docs don't
    guarantee a 5xx means nothing was queued for delivery, so this is
    not automatically retried either."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"ok": False, "description": "Service Unavailable"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(TelegramSendError) as exc_info:
        await send_message(client, bot_token="tok", chat_id="1", text="hi")

    assert not isinstance(exc_info.value, TelegramTransientError)


async def test_a_definitive_rejection_is_not_a_transient_error() -> None:
    """A permanent rejection (bad chat_id) must not be retried by
    telegram_relay.py — it must raise the base TelegramSendError, not
    the TelegramTransientError subclass."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "chat not found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(TelegramSendError) as exc_info:
        await send_message(client, bot_token="tok", chat_id="missing", text="hi")

    assert not isinstance(exc_info.value, TelegramTransientError)
