"""Audit event recording — FR-AUD-001/004.

Every sensitive application-layer action must call `record_audit_event`
inside the same transaction as the domain change it describes, so an event
never gets written for a change that then rolls back.

The hash chain is serialized per customer via AuditChainTip: an upsert
guarantees the tip row exists, then SELECT ... FOR UPDATE locks it before
the next hash is computed, so two concurrent writers for the same customer
queue up instead of both reading the same prev_hash and forking the chain.
Different customers still write in parallel — they lock different rows.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from doda.application.hashing import canonical_json, hash_payload
from doda.domain.audit.models import AuditChainTip, AuditEvent
from doda.domain.base import utcnow


async def record_audit_event(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    trace_id: uuid.UUID,
    actor_id: str,
    event_type: str,
    safe_metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    safe_metadata = safe_metadata or {}

    await session.execute(
        pg_insert(AuditChainTip)
        .values(customer_id=customer_id, tip_hash=None)
        .on_conflict_do_nothing(index_elements=["customer_id"])
    )
    tip = await session.scalar(
        select(AuditChainTip).where(AuditChainTip.customer_id == customer_id).with_for_update()
    )
    assert tip is not None  # the upsert above guarantees this row exists

    occurred_at = utcnow()
    digest = hash_payload(
        {
            "customer_id": str(customer_id),
            "trace_id": str(trace_id),
            "actor_id": actor_id,
            "event_type": event_type,
            "occurred_at": occurred_at.isoformat(),
            "safe_metadata": canonical_json(safe_metadata),
            "prev_hash": tip.tip_hash,
        }
    )
    event = AuditEvent(
        customer_id=customer_id,
        trace_id=trace_id,
        actor_id=actor_id,
        event_type=event_type,
        occurred_at=occurred_at,
        safe_metadata=safe_metadata,
        prev_hash=tip.tip_hash,
        hash=digest,
    )
    session.add(event)
    tip.tip_hash = digest
    await session.flush()
    return event
