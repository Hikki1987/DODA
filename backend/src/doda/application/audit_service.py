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
from dataclasses import dataclass
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
    workspace_id: uuid.UUID | None = None,
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
            "workspace_id": str(workspace_id) if workspace_id else None,
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
        workspace_id=workspace_id,
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


@dataclass(frozen=True)
class AuditChainViolation:
    """One broken link found by `verify_audit_chain` (FR-AUD-004)."""

    event_id: uuid.UUID
    reason: str


@dataclass(frozen=True)
class AuditChainVerificationResult:
    checked_count: int
    violations: list[AuditChainViolation]

    @property
    def ok(self) -> bool:
        return len(self.violations) == 0


async def verify_audit_chain(
    session: AsyncSession, *, customer_id: uuid.UUID
) -> AuditChainVerificationResult:
    """Walk this customer's audit events in the order they were written and
    recompute each one's hash from its own stored fields plus the previous
    event's stored hash, comparing against what is actually stored.

    Read-only — this detects tampering (FR-AUD-004: "buzilishda alert"), it
    never repairs a row. An empty return means the chain is intact.

    Ordered by (created_at, id) — the same tie-broken ordering
    `audit_query_service.list_audit_events` already uses for pagination —
    which matches true write order because `record_audit_event` serializes
    writes per customer via `AuditChainTip`'s row lock.
    """
    events = (
        await session.scalars(
            select(AuditEvent)
            .where(AuditEvent.customer_id == customer_id)
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        )
    ).all()

    violations = []
    expected_prev_hash: str | None = None
    for event in events:
        if event.prev_hash != expected_prev_hash:
            violations.append(AuditChainViolation(event_id=event.id, reason="prev_hash_mismatch"))

        recomputed = hash_payload(
            {
                "customer_id": str(event.customer_id),
                "workspace_id": str(event.workspace_id) if event.workspace_id else None,
                "trace_id": str(event.trace_id),
                "actor_id": event.actor_id,
                "event_type": event.event_type,
                "occurred_at": event.occurred_at.isoformat(),
                "safe_metadata": canonical_json(event.safe_metadata),
                "prev_hash": event.prev_hash,
            }
        )
        if recomputed != event.hash:
            violations.append(AuditChainViolation(event_id=event.id, reason="hash_mismatch"))

        # Continue walking from this event's *stored* hash even when it
        # didn't validate, so one bad row is reported once and doesn't
        # cascade into a false "prev_hash_mismatch" for every row after it.
        expected_prev_hash = event.hash

    return AuditChainVerificationResult(checked_count=len(events), violations=violations)
