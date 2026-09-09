"""Outbox relay — ADR-003. Polls unpublished outbox_messages and hands each
to a transport (a Redis Stream here, per section 6.3 "Redis + worker
abstraksiyasi"). This is a platform-level process and intentionally reads
across all tenants — see doda.domain.outbox.models for why RLS does not
apply to this table.

`FOR UPDATE SKIP LOCKED` lets multiple relay workers run concurrently
without double-processing a row. `published_at` is only set after a
successful publish, so a crash between publish and commit can redeliver
(at-least-once) — the eventual connector consumer must itself be
idempotent on the message id, matching FR-ACT-004's spirit for outbound
delivery too.

The first such connector now exists (OD-002: Telegram) —
see infrastructure/telegram_relay.py, which reads this module's own
`doda:outbox:action.ready.v1` output stream and is itself idempotent on
redelivery. Every other tool_name still has no connector consuming its
READY actions; this module alone still only proves the outbox ->
transport leg for those.

`run_forever`/`main` are the actual worker entrypoint (ADR-001's "alohida
worker"): until this was added, `relay_once` was only ever called from
tests — there was no process anywhere in this codebase (or in
docker-compose.yml) that ever polled the outbox continuously, so no
outbox message would ever have been delivered in a real running
deployment. `python -m doda.infrastructure.outbox_relay` now runs it.
"""

import asyncio
import contextlib
import json
import signal
from datetime import UTC, datetime

import structlog
from redis.asyncio import Redis
from sqlalchemy import select

from doda.config import get_settings
from doda.db import async_session_factory
from doda.domain.outbox.models import OutboxMessage

logger = structlog.get_logger()

DEFAULT_BATCH_SIZE = 50
DEFAULT_POLL_INTERVAL_SECONDS = 1.0


async def relay_once(redis: Redis, *, batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    """Publish up to `batch_size` pending messages. Returns how many were sent."""
    published = 0
    async with async_session_factory() as session, session.begin():
        result = await session.execute(
            select(OutboxMessage)
            .where(OutboxMessage.published_at.is_(None))
            .order_by(OutboxMessage.created_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        for message in result.scalars():
            stream = f"doda:outbox:{message.event_type}"
            await redis.xadd(
                stream,
                {
                    "id": str(message.id),
                    "customer_id": str(message.customer_id),
                    "aggregate_type": message.aggregate_type,
                    "aggregate_id": str(message.aggregate_id),
                    "payload": json.dumps(message.payload),
                },
            )
            message.published_at = datetime.now(UTC)
            message.attempts += 1
            published += 1
    return published


async def run_forever(
    redis: Redis,
    *,
    stop_event: asyncio.Event,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
    """Poll `relay_once` until `stop_event` is set.

    Drains immediately (no sleep) after a batch that published at least one
    message — there may be more waiting right behind it — and only sleeps
    `poll_interval` when a poll finds nothing, so an idle relay doesn't spin
    the CPU. The sleep is a `stop_event.wait()` with a timeout rather than a
    plain `asyncio.sleep`, so a shutdown signal during an idle period is
    honored immediately instead of waiting out the rest of the interval.
    """
    while not stop_event.is_set():
        published = await relay_once(redis, batch_size=batch_size)
        if published:
            logger.info("outbox_relay.published", count=published)
        else:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)


async def main() -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    logger.info("outbox_relay.starting")
    try:
        await run_forever(redis, stop_event=stop_event)
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)
        await redis.aclose()
        logger.info("outbox_relay.stopped")


if __name__ == "__main__":
    asyncio.run(main())
