import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from doda.domain.outbox.models import OutboxMessage


async def enqueue_outbox_message(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
) -> OutboxMessage:
    """Insert an outbox row. Caller must do this inside the same transaction
    as the domain change it announces — see doda.domain.outbox.models."""
    message = OutboxMessage(
        customer_id=customer_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
    )
    session.add(message)
    await session.flush()
    return message
