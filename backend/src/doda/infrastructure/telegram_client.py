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
    """A Telegram send failed — network error, non-2xx response, or an
    `ok: false` API response. The message is safe to log: see module
    docstring."""


@dataclasses.dataclass(frozen=True)
class TelegramSendResult:
    message_id: int


async def send_message(
    http_client: httpx.AsyncClient, *, bot_token: str, chat_id: str, text: str
) -> TelegramSendResult:
    """POST to Telegram's sendMessage endpoint. Raises TelegramSendError on
    any network failure, non-2xx response, or `{"ok": false, ...}` body."""
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    try:
        response = await http_client.post(url, json={"chat_id": chat_id, "text": text}, timeout=10.0)
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise TelegramSendError(f"Telegram request failed: {type(exc).__name__}") from None

    if not response.is_success or not body.get("ok"):
        raise TelegramSendError(
            f"Telegram API rejected the message: HTTP {response.status_code}, "
            f"description={body.get('description', '<none>')!r}"
        )

    return TelegramSendResult(message_id=body["result"]["message_id"])
