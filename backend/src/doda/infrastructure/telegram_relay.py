"""Telegram connector — the first real consumer of the outbox relay's
Redis Stream (ADR-003, ADR-007/OD-002).

Until this module, `outbox_relay.py`'s own docstring said it plainly:
"connector does not exist yet (S7)" — action.ready.v1 messages reached a
Redis Stream and nothing ever read them. This is that missing consumer,
scoped to exactly the one tool a Product Owner decision has actually
targeted (`telegram.send_message`, domain/action/tool_policy.py). Every
other tool_name is left alone — XACK'd without action — this is not a
general-purpose action executor.

Closes the traceability-audit gap on FR-ACT (RUNNING/SUCCEEDED/FAILED
were valid `state_machine.py` transitions that no code path ever used):
`apply_transition` now actually drives READY -> RUNNING -> SUCCEEDED/
FAILED for this one connector, reusing the exact same audit+locking
chokepoint every other transition in this codebase goes through.

Idempotency (a stream entry can be redelivered — consumer crash before
XACK, consumer-group semantics) has two independent layers, proven
separately (see test_telegram_relay.py's redelivery test and its own
revert-test-restore note): (1) `_drive_to_running`'s own status check —
anything other than READY is treated as "a previous delivery already
handled this" and skipped cleanly (XACK'd, no exception, no re-send);
(2) even with that check removed, `apply_transition`'s state machine
independently refuses e.g. SUCCEEDED -> RUNNING (`InvalidActionTransition`),
so a redelivered entry still cannot reach `send_message` a second time —
it just does so noisily (an uncaught exception that leaves the entry
un-ACK'd in the PEL) rather than being skipped cleanly. Layer (1) is
the intended, quiet path; layer (2) is the backstop if it's ever
removed or has a bug, matching this codebase's existing "second,
independent layer" pattern (ADR-005).

Neither layer closes the ONE narrower gap that's real: a crash between
a successful Telegram call and this process's own commit of the
SUCCEEDED transition would leave the message sent but the Action stuck
in RUNNING (redelivery sees RUNNING != READY and skips, so it is never
re-sent, but also never resolved to SUCCEEDED without a separate
reconciliation job). That reconciliation job is real future work, not
solved here — recorded honestly rather than silently assumed away,
since Telegram's Bot API itself has no request-level idempotency key to
close it more directly. `scripts/find_stuck_running_actions.py` makes
this gap observable (an Action stuck in RUNNING past a threshold is
reported, exit code 1) without attempting to resolve it — resolving it
still needs the design decision above, not a monitoring script.

Honest limitation on THIS PR's own verification: no real Telegram bot
token or chat is available in this environment, so the actual HTTP call
to Telegram's API has not been exercised against the real service here
-- only the outbox -> Redis Stream -> this consumer -> DB state
transition pipeline is proven against real Postgres+Redis, with the
Telegram HTTP leg itself under test doubles. See
tests/integration/test_telegram_relay.py for exactly what is and isn't
covered.
"""

import asyncio
import signal
import uuid
from typing import cast

import httpx
import structlog
from redis.asyncio import Redis

from doda.application.action_service import apply_transition
from doda.config import get_settings
from doda.db import tenant_scoped_session
from doda.domain.action.models import Action, ActionStatus
from doda.infrastructure.telegram_client import TelegramSendError, send_message

logger = structlog.get_logger()

STREAM_NAME = "doda:outbox:action.ready.v1"
CONSUMER_GROUP = "telegram-connector"
CONSUMER_NAME = "telegram-connector-1"
TELEGRAM_TOOL_NAME = "telegram.send_message"
DEFAULT_BLOCK_MS = 1000
ACTOR_ID = "system:telegram_connector"


async def ensure_consumer_group(redis: Redis) -> None:
    """Create the consumer group (and the stream, if it doesn't exist yet)
    starting from the beginning of the stream. Safe to call every startup —
    Redis rejects re-creating an existing group with BUSYGROUP, which is
    not an error here."""
    try:
        await redis.xgroup_create(STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def _drive_to_running(customer_id: uuid.UUID, action_id: uuid.UUID) -> Action | None:
    """READY -> RUNNING in its own committed transaction, so a crash after
    this point never causes a re-send on redelivery (see module docstring).
    Returns the action's payload dict if it was READY and is now RUNNING,
    None if this delivery should be skipped (not ours, or already past
    READY)."""
    async with tenant_scoped_session(customer_id) as session:
        action = await session.get(Action, action_id)
        if action is None or action.tool_name != TELEGRAM_TOOL_NAME:
            return None
        if action.status is not ActionStatus.READY:
            logger.info("telegram_relay.skip_not_ready", action_id=str(action_id), status=action.status.value)
            return None
        await apply_transition(session, action, ActionStatus.RUNNING, actor_id=ACTOR_ID)
        return action


async def _resolve(customer_id: uuid.UUID, action_id: uuid.UUID, target: ActionStatus) -> None:
    async with tenant_scoped_session(customer_id) as session:
        action = await session.get(Action, action_id)
        assert action is not None  # we just committed it into existence above
        await apply_transition(session, action, target, actor_id=ACTOR_ID)


async def process_entry(
    http_client: httpx.AsyncClient, *, fields: dict[bytes, bytes], bot_token: str | None
) -> None:
    customer_id = uuid.UUID(fields[b"customer_id"].decode())
    action_id = uuid.UUID(fields[b"aggregate_id"].decode())

    running_action = await _drive_to_running(customer_id, action_id)
    if running_action is None:
        return

    if bot_token is None:
        logger.error("telegram_relay.no_bot_token_configured", action_id=str(action_id))
        await _resolve(customer_id, action_id, ActionStatus.FAILED)
        return

    chat_id = running_action.payload.get("chat_id")
    text = running_action.payload.get("text")
    if not isinstance(chat_id, str) or not isinstance(text, str):
        logger.error("telegram_relay.malformed_payload", action_id=str(action_id))
        await _resolve(customer_id, action_id, ActionStatus.FAILED)
        return

    try:
        await send_message(http_client, bot_token=bot_token, chat_id=chat_id, text=text)
    except TelegramSendError as exc:
        logger.warning("telegram_relay.send_failed", action_id=str(action_id), reason=str(exc))
        await _resolve(customer_id, action_id, ActionStatus.FAILED)
        return

    await _resolve(customer_id, action_id, ActionStatus.SUCCEEDED)


async def relay_once(redis: Redis, http_client: httpx.AsyncClient, *, bot_token: str | None) -> int:
    """Read and process up to one batch of pending entries. Returns how many
    were read (processed or deliberately skipped) — 0 means nothing new.

    Ensures the consumer group exists on every call (cheap: a single
    BUSYGROUP-tolerant XGROUP CREATE) rather than requiring every caller
    to remember to call `ensure_consumer_group` first — `run_forever`
    does it too, but a caller invoking `relay_once` directly (every test
    in this module) should not have to know that detail to get a
    correct result instead of a NOGROUP error."""
    await ensure_consumer_group(redis)
    # redis-py's own stubs type xreadgroup's return far more loosely than
    # its actual shape (a list of (stream_name, [(entry_id, fields), ...])
    # pairs) -- cast rather than leave the whole function unannotated.
    response = cast(
        list[tuple[bytes, list[tuple[bytes, dict[bytes, bytes]]]]],
        await redis.xreadgroup(
            CONSUMER_GROUP, CONSUMER_NAME, {STREAM_NAME: ">"}, count=50, block=DEFAULT_BLOCK_MS
        ),
    )
    if not response:
        return 0

    processed = 0
    for _stream_name, entries in response:
        for entry_id, fields in entries:
            try:
                await process_entry(http_client, fields=fields, bot_token=bot_token)
            except Exception:
                logger.exception("telegram_relay.entry_failed", entry_id=entry_id)
                continue  # leave un-ACK'd — stays in the PEL for reconciliation, not silently dropped
            await redis.xack(STREAM_NAME, CONSUMER_GROUP, entry_id)
            processed += 1
    return processed


async def run_forever(
    redis: Redis,
    http_client: httpx.AsyncClient,
    *,
    stop_event: asyncio.Event,
    bot_token: str | None,
) -> None:
    """`xreadgroup`'s own `block=DEFAULT_BLOCK_MS` already bounds each
    `relay_once` call to ~1s when the stream is idle, so `stop_event` is
    checked at least that often without a separate timeout wrapper (the
    same shutdown-latency shape as outbox_relay.py's `poll_interval`).
    `relay_once` itself ensures the consumer group exists on every call,
    so this loop doesn't need to do it separately."""
    while not stop_event.is_set():
        await relay_once(redis, http_client, bot_token=bot_token)


async def main() -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    if settings.telegram_bot_token is None:
        logger.warning("telegram_relay.starting_without_bot_token")
    logger.info("telegram_relay.starting")
    try:
        async with httpx.AsyncClient() as http_client:
            await run_forever(
                redis, http_client, stop_event=stop_event, bot_token=settings.telegram_bot_token
            )
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)
        await redis.aclose()
        logger.info("telegram_relay.stopped")


if __name__ == "__main__":
    asyncio.run(main())
