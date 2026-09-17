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
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from doda.application.audit_query_service import list_audit_events_for_trace
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


def _recompute_event_hash(event: AuditEvent) -> str:
    """The exact same formula `record_audit_event` used to mint
    `event.hash` in the first place — shared by `verify_audit_chain` and
    `build_evidence_package` so the two can never quietly diverge."""
    return hash_payload(
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

        recomputed = _recompute_event_hash(event)
        if recomputed != event.hash:
            violations.append(AuditChainViolation(event_id=event.id, reason="hash_mismatch"))

        # Continue walking from this event's *stored* hash even when it
        # didn't validate, so one bad row is reported once and doesn't
        # cascade into a false "prev_hash_mismatch" for every row after it.
        expected_prev_hash = event.hash

    return AuditChainVerificationResult(checked_count=len(events), violations=violations)


@dataclass(frozen=True)
class EvidenceEvent:
    """One audit event as it appears in an evidence package — the same
    fields `_recompute_event_hash` needs, plus the recomputation result
    itself, so a recipient can see BOTH the stored hash and whether this
    codebase's own recomputation (from the event's own fields) confirms
    it, without needing DB access or trusting the claim blindly."""

    id: uuid.UUID
    event_type: str
    actor_id: str
    workspace_id: uuid.UUID | None
    occurred_at: datetime
    safe_metadata: dict[str, Any]
    prev_hash: str | None
    hash: str
    hash_self_consistent: bool


@dataclass(frozen=True)
class EvidencePackage:
    """FR-AUD-005: "Evidence paketini eksport qilish (trace + natija +
    hash) — eksport qayta tekshiriladigan hash bilan keladi."

    Two, deliberately DIFFERENT integrity claims, not to be conflated:
    - `events[i].hash_self_consistent` proves that specific event's own
      content was not altered after being written (recomputed from its
      own stored fields).
    - `full_chain_verification` (the existing, whole-customer
      `verify_audit_chain` result) proves nothing was inserted, deleted,
      or reordered anywhere in the chain around these events — a trace's
      own events are almost never contiguous in the full chain (other,
      unrelated events interleave chronologically), so re-chaining just
      the trace subset against itself would prove nothing; the full-chain
      check is the only thing that actually can.
    """

    customer_id: uuid.UUID
    trace_id: uuid.UUID
    events: list[EvidenceEvent]
    full_chain_verification: AuditChainVerificationResult


async def build_evidence_package(
    session: AsyncSession, *, customer_id: uuid.UUID, trace_id: uuid.UUID
) -> EvidencePackage:
    events = await list_audit_events_for_trace(session, customer_id=customer_id, trace_id=trace_id)
    evidence_events = [
        EvidenceEvent(
            id=event.id,
            event_type=event.event_type,
            actor_id=event.actor_id,
            workspace_id=event.workspace_id,
            occurred_at=event.occurred_at,
            safe_metadata=event.safe_metadata,
            prev_hash=event.prev_hash,
            hash=event.hash,
            hash_self_consistent=_recompute_event_hash(event) == event.hash,
        )
        for event in events
    ]
    full_chain_verification = await verify_audit_chain(session, customer_id=customer_id)
    return EvidencePackage(
        customer_id=customer_id,
        trace_id=trace_id,
        events=evidence_events,
        full_chain_verification=full_chain_verification,
    )
