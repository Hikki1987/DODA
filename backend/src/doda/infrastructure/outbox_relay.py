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
delivery too. That connector does not exist yet (S7); this module only
proves the outbox -> transport leg of the pattern.
"""

import json
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select

from doda.db import async_session_factory
from doda.domain.outbox.models import OutboxMessage

DEFAULT_BATCH_SIZE = 50


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
