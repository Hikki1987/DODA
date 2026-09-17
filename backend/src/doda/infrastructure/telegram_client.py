"""Telegram Bot API client — OD-002's first real connector target.

Deliberately minimal: this project's only registered use of Telegram is
`telegram.send_message` (see domain/action/tool_policy.py). No polling,
webhooks, or other Bot API methods are implemented until a real need for
them exists.

Security note: Telegram's Bot API puts the bot token in the URL path
itself (`/bot<token>/method`), not a header. That means the token would
leak into any log line or exception message that includes the raw
request URL or a bare `str(exc)` on an httpx error (httpx's own error
messages embed the URL). Every error path here is written to avoid
that — `TelegramSendError`'s message never includes the URL or the
underlying httpx exception's own string form, only its type name.
"""

import dataclasses

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramSendError(Exception):
    """A Telegram send failed in a way that will not succeed on retry — a
    definitive API rejection (bad chat_id, forbidden, malformed request,
    ...). The message is safe to log: see module docstring."""


class TelegramTransientError(TelegramSendError):
    """FR-ACT-005 (Must): a Telegram send failed for a reason that MIGHT
    succeed on retry — a network error, a timeout, an unparseable
    response, HTTP 429 (rate limited), or a 5xx server error. This is a
    TelegramSendError subclass, so existing callers that only catch the
    base class are unaffected; infrastructure/telegram_relay.py catches
    this subclass specifically to retry with backoff before giving up."""


@dataclasses.dataclass(frozen=True)
class TelegramSendResult:
    message_id: int


async def send_message(
    http_client: httpx.AsyncClient, *, bot_token: str, chat_id: str, text: str
) -> TelegramSendResult:
    """POST to Telegram's sendMessage endpoint. Raises TelegramTransientError
    for a failure that is plausibly retryable (network error, timeout,
    unparseable response, HTTP 429, or a 5xx), and the base
    TelegramSendError for a definitive rejection (any other non-2xx or
    `ok: false`)."""
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    try:
        response = await http_client.post(url, json={"chat_id": chat_id, "text": text}, timeout=10.0)
    except httpx.HTTPError as exc:
        raise TelegramTransientError(f"Telegram request failed: {type(exc).__name__}") from None

    if response.status_code == 429 or response.status_code >= 500:
        raise TelegramTransientError(f"Telegram API is temporarily unavailable: HTTP {response.status_code}")

    try:
        body = response.json()
    except ValueError as exc:
        raise TelegramTransientError(f"Telegram response was not valid JSON: {type(exc).__name__}") from None

    if not response.is_success or not body.get("ok"):
        raise TelegramSendError(
            f"Telegram API rejected the message: HTTP {response.status_code}, "
            f"description={body.get('description', '<none>')!r}"
        )

    return TelegramSendResult(message_id=body["result"]["message_id"])
