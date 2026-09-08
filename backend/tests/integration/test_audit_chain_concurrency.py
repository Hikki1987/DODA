"""Proves the FR-AUD-004 concurrency fix: N concurrent record_audit_event
calls for the SAME customer must produce one unbroken hash chain, never a
fork. This is the test that would have failed against the old
"ORDER BY created_at DESC LIMIT 1, no lock" implementation — two
concurrent transactions could both read the same prev_hash.

Verification is timestamp-independent by design (real chain-order
reconstruction from the hash links themselves, not from created_at, which
concurrent transactions can't be trusted to order reliably): a valid,
unforked chain has exactly one root (prev_hash IS NULL) and every other
event's prev_hash is unique among all events and points to another event
in the same set.
"""

import asyncio
import uuid

from sqlalchemy import select

from doda.application.audit_service import record_audit_event
from doda.db import tenant_scoped_session
from doda.domain.audit.models import AuditEvent

CONCURRENT_WRITERS = 12


async def test_concurrent_audit_writes_for_same_customer_do_not_fork_the_chain(
    db_available: bool,
) -> None:
    customer_id = uuid.uuid4()
    trace_id = uuid.uuid4()

    async def write(i: int) -> None:
        async with tenant_scoped_session(customer_id) as session:
            await record_audit_event(
                session,
                customer_id=customer_id,
                trace_id=trace_id,
                actor_id="user:concurrent-writer",
                event_type=f"test.concurrent.{i}.v1",
            )

    await asyncio.gather(*(write(i) for i in range(CONCURRENT_WRITERS)))

    async with tenant_scoped_session(customer_id) as session:
        events = (
            (await session.execute(select(AuditEvent).where(AuditEvent.customer_id == customer_id)))
            .scalars()
            .all()
        )

    assert len(events) == CONCURRENT_WRITERS

    hashes = {e.hash for e in events}
    assert len(hashes) == CONCURRENT_WRITERS  # every hash distinct

    prev_hashes = [e.prev_hash for e in events]
    assert prev_hashes.count(None) == 1  # exactly one root — no two events both "went first"

    non_root_prev_hashes = [p for p in prev_hashes if p is not None]
    assert len(non_root_prev_hashes) == len(
        set(non_root_prev_hashes)
    )  # no hash claimed by two children (fork)
    assert set(non_root_prev_hashes) <= hashes  # every parent link resolves within this chain
