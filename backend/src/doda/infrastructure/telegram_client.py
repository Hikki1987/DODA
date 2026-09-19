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
    """FR-ACT-005 (Must): a Telegram send failed for a reason that is KNOWN
    to have happened before Telegram could have queued the message for
    delivery — the connection could not even be established (or timed
    out trying), or Telegram's own 429 rejected the request outright.
    This is a TelegramSendError subclass, so existing callers that only
    catch the base class are unaffected; infrastructure/telegram_relay.py
    catches this subclass specifically to retry with backoff before
    giving up.

    Deliberately NOT raised for a read/write timeout or a 5xx: once a
    request has actually been written to the wire, this client cannot
    tell "definitely not delivered" from "delivered, we just didn't see
    the response" — UC-004's own mandated negative scenario, "provider
    timeout bergan lekin xat aslida yuborilgan" (the provider timed out,
    but the message was actually sent). Telegram's Bot API has no
    request-level idempotency key (see telegram_relay.py's own
    docstring), so retrying an ambiguous failure risks a real duplicate
    message to a real chat — worse than a false FAILED that a human can
    re-check. Those cases raise the non-retryable base TelegramSendError
    instead, on purpose."""


@dataclasses.dataclass(frozen=True)
class TelegramSendResult:
    message_id: int


async def send_message(
    http_client: httpx.AsyncClient, *, bot_token: str, chat_id: str, text: str
) -> TelegramSendResult:
    """POST to Telegram's sendMessage endpoint. Raises TelegramTransientError
    only for a failure known to have happened before Telegram could have
    queued anything (a connection failure, or an explicit 429 rejection),
    and the base, non-retryable TelegramSendError for everything else —
    including a read/write timeout or a 5xx, where whether the message
    was actually sent is genuinely ambiguous (see TelegramTransientError's
    own docstring)."""
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    try:
        response = await http_client.post(url, json={"chat_id": chat_id, "text": text}, timeout=10.0)
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
        raise TelegramTransientError(f"Telegram request failed: {type(exc).__name__}") from None
    except httpx.HTTPError as exc:
        raise TelegramSendError(f"Telegram request failed ambiguously: {type(exc).__name__}") from None

    if response.status_code == 429:
        raise TelegramTransientError(f"Telegram API is temporarily unavailable: HTTP {response.status_code}")

    try:
        body = response.json()
    except ValueError as exc:
        raise TelegramSendError(f"Telegram response was not valid JSON: {type(exc).__name__}") from None

    if not response.is_success or not body.get("ok"):
        raise TelegramSendError(
            f"Telegram API rejected the message: HTTP {response.status_code}, "
            f"description={body.get('description', '<none>')!r}"
        )

    return TelegramSendResult(message_id=body["result"]["message_id"])
