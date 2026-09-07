"""Audit event recording — FR-AUD-001/004.

Every sensitive application-layer action must call `record_audit_event`
inside the same transaction as the domain change it describes, so an event
never gets written for a change that then rolls back.

KNOWN LIMITATION: chaining `prev_hash` off "the last row for this customer"
is correct for serial writes but is not safe under concurrent writers for
the same customer — two concurrent transactions could read the same
"latest" row and both chain off it, forking the hash chain. Production
hardening needs a per-customer chain-tip row locked with SELECT ... FOR
UPDATE before computing the next hash. Acceptable for the current
single-writer-per-customer MVP shape; must be revisited before FR-AUD-004's
"kunlik verification job" is built (section 12.4 / NFR-AUD-004).
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doda.application.hashing import canonical_json, hash_payload
from doda.domain.audit.models import AuditEvent
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
    prev_hash = await session.scalar(
        select(AuditEvent.hash)
        .where(AuditEvent.customer_id == customer_id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )
    occurred_at = utcnow()
    digest = hash_payload(
        {
            "customer_id": str(customer_id),
            "trace_id": str(trace_id),
            "actor_id": actor_id,
            "event_type": event_type,
            "occurred_at": occurred_at.isoformat(),
            "safe_metadata": canonical_json(safe_metadata),
            "prev_hash": prev_hash,
        }
    )
    event = AuditEvent(
        customer_id=customer_id,
        trace_id=trace_id,
        actor_id=actor_id,
        event_type=event_type,
        occurred_at=occurred_at,
        safe_metadata=safe_metadata,
        prev_hash=prev_hash,
        hash=digest,
    )
    session.add(event)
    await session.flush()
    return event
