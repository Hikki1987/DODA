"""FR-AUD-004 — "Integrity chain (hash zanjiri) va davriy tekshiruv":
verify_audit_chain must report a clean chain as clean, and must pinpoint a
tampered row rather than just noticing "something is wrong somewhere" —
proven here with a real, direct row mutation (not a synthetic call), the
same discipline used for the concurrency fix in
test_audit_chain_concurrency.py.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from doda.application.audit_service import record_audit_event, verify_audit_chain
from doda.application.customer_service import create_customer_with_owner, invite_customer_member
from doda.application.hashing import canonical_json, hash_payload
from doda.application.session_service import create_session
from doda.db import tenant_scoped_session
from doda.domain.audit.models import AuditEvent
from doda.domain.base import utcnow
from doda.domain.identity.models import AuthStrength, User
from doda.domain.security.roles import CustomerRole
from doda.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_headers(session_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


async def test_untampered_chain_verifies_clean(db_available: bool) -> None:
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        for i in range(5):
            await record_audit_event(
                session,
                customer_id=customer_id,
                trace_id=uuid.uuid4(),
                actor_id="user:writer",
                event_type=f"test.event.{i}.v1",
            )

    async with tenant_scoped_session(customer_id) as session:
        result = await verify_audit_chain(session, customer_id=customer_id)

    assert result.ok
    assert result.checked_count == 5
    assert result.violations == []


async def test_tampered_event_is_detected_and_pinpointed(db_available: bool) -> None:
    """`audit_events_no_update_delete` (migration 0001) already blocks
    UPDATE/DELETE on this table outright — proven incidentally by this test:
    an ORM-level row mutation here raises `RaiseError('audit_events is
    append-only...')` before verify_audit_chain is ever reached. So the
    realistic tamper vector `verify_audit_chain` actually guards against is
    a rogue direct INSERT that bypasses `record_audit_event` (e.g. a bug in
    some future code path, or a forged historical row) — the trigger has no
    opinion on INSERT, only this function does.
    """
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        for i in range(4):
            await record_audit_event(
                session,
                customer_id=customer_id,
                trace_id=uuid.uuid4(),
                actor_id="user:writer",
                event_type=f"test.event.{i}.v1",
            )
        real_tip = (
            await session.execute(
                select(AuditEvent.hash)
                .where(AuditEvent.customer_id == customer_id)
                .order_by(AuditEvent.created_at.desc())
                .limit(1)
            )
        ).scalar_one()

        forged = AuditEvent(
            customer_id=customer_id,
            trace_id=uuid.uuid4(),
            actor_id="user:attacker",
            event_type="test.forged.v1",
            occurred_at=utcnow(),
            safe_metadata={},
            prev_hash=real_tip,  # correctly chains onto the real tip...
            hash="0" * 64,  # ...but its own hash was never actually computed from its content.
        )
        session.add(forged)
        await session.flush()
        forged_id = forged.id

    async with tenant_scoped_session(customer_id) as session:
        result = await verify_audit_chain(session, customer_id=customer_id)

    assert not result.ok
    assert result.checked_count == 5
    violation_event_ids = {v.event_id for v in result.violations}
    assert violation_event_ids == {forged_id}
    assert result.violations[0].reason == "hash_mismatch"


async def test_broken_chain_link_is_detected_and_pinpointed(db_available: bool) -> None:
    """The companion to the hash_mismatch test above: a row whose own `hash`
    is correctly computed from its content (so that check alone would pass)
    but whose `prev_hash` does not match the actual preceding event's
    stored hash — the chain-linkage check `verify_audit_chain` makes
    independently of the per-row hash check. Left unexercised until now
    (CLAUDE.md's coverage notes) because producing it means deliberately
    forging a plausible-but-wrong link, not a one-line mutation.
    """
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        for i in range(4):
            await record_audit_event(
                session,
                customer_id=customer_id,
                trace_id=uuid.uuid4(),
                actor_id="user:writer",
                event_type=f"test.event.{i}.v1",
            )

        wrong_prev_hash = "f" * 64  # well-formed, but not the real tip below
        trace_id = uuid.uuid4()
        occurred_at = utcnow()
        forged = AuditEvent(
            customer_id=customer_id,
            trace_id=trace_id,
            actor_id="user:attacker",
            event_type="test.forged.v1",
            occurred_at=occurred_at,
            safe_metadata={},
            prev_hash=wrong_prev_hash,
            hash=hash_payload(
                {
                    "customer_id": str(customer_id),
                    "workspace_id": None,
                    "trace_id": str(trace_id),
                    "actor_id": "user:attacker",
                    "event_type": "test.forged.v1",
                    "occurred_at": occurred_at.isoformat(),
                    "safe_metadata": canonical_json({}),
                    "prev_hash": wrong_prev_hash,
                }
            ),
        )
        session.add(forged)
        await session.flush()
        forged_id = forged.id

    async with tenant_scoped_session(customer_id) as session:
        result = await verify_audit_chain(session, customer_id=customer_id)

    assert not result.ok
    assert result.checked_count == 5
    violation_event_ids = {v.event_id for v in result.violations}
    assert violation_event_ids == {forged_id}
    assert result.violations[0].reason == "prev_hash_mismatch"


async def test_only_customer_owner_or_auditor_may_verify_the_chain_over_http(
    client: AsyncClient, db_available: bool
) -> None:
    owner_user_id = uuid.uuid4()
    member_user_id = uuid.uuid4()
    auditor_user_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        session.add_all(
            [
                User(id=owner_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Owner"),
                User(id=member_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Member"),
                User(id=auditor_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Auditor"),
            ]
        )
        await session.flush()
        await create_customer_with_owner(
            session, customer_id=customer_id, name="Acme", owner_user_id=owner_user_id, actor_id="user:setup"
        )
        await invite_customer_member(
            session,
            customer_id=customer_id,
            user_id=member_user_id,
            role=CustomerRole.MEMBER,
            actor_id="user:setup",
        )
        await invite_customer_member(
            session,
            customer_id=customer_id,
            user_id=auditor_user_id,
            role=CustomerRole.AUDITOR,
            actor_id="user:setup",
        )
        owner_session = await create_session(session, user_id=owner_user_id, auth_strength=AuthStrength.AAL1)
        member_session = await create_session(
            session, user_id=member_user_id, auth_strength=AuthStrength.AAL1
        )
        auditor_session = await create_session(
            session, user_id=auditor_user_id, auth_strength=AuthStrength.AAL1
        )

    owner_response = await client.get(
        f"/v1/customers/{customer_id}/audit/verify", headers=_auth_headers(owner_session.id)
    )
    assert owner_response.status_code == 200
    body = owner_response.json()
    assert body["ok"] is True
    assert body["checked_count"] >= 1  # at least customer.created.v1
    assert body["violations"] == []

    auditor_response = await client.get(
        f"/v1/customers/{customer_id}/audit/verify", headers=_auth_headers(auditor_session.id)
    )
    assert auditor_response.status_code == 200

    member_response = await client.get(
        f"/v1/customers/{customer_id}/audit/verify", headers=_auth_headers(member_session.id)
    )
    assert member_response.status_code == 403
    assert member_response.json()["code"] == "DENY"


async def test_verifying_the_chain_is_itself_audited(client: AsyncClient, db_available: bool) -> None:
    owner_user_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        session.add(User(id=owner_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Owner"))
        await session.flush()
        await create_customer_with_owner(
            session, customer_id=customer_id, name="Acme", owner_user_id=owner_user_id, actor_id="user:setup"
        )
        owner_session = await create_session(session, user_id=owner_user_id, auth_strength=AuthStrength.AAL1)

    verify_response = await client.get(
        f"/v1/customers/{customer_id}/audit/verify", headers=_auth_headers(owner_session.id)
    )
    assert verify_response.status_code == 200

    audit_response = await client.get(
        f"/v1/customers/{customer_id}/audit", headers=_auth_headers(owner_session.id)
    )
    event_types = [e["event_type"] for e in audit_response.json()]
    assert "audit.chain_verified.v1" in event_types


async def test_audit_events_reject_update_and_delete(db_available: bool) -> None:
    """FR-AUD-001/004's append-only property, asserted rather than observed.

    The `audit_events_no_update_delete` trigger (migration 0001) is the thing
    that makes the hash chain worth verifying at all — a chain you can rewrite
    in place proves nothing. Until now no test touched it: the tamper test
    above only mentions, in passing, that an UPDATE raised the trigger's error
    while it was being written. So a migration that dropped the trigger, or a
    downgrade that left it off, would have taken the whole property with it
    and every test would still have passed.
    """
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        event = await record_audit_event(
            session,
            customer_id=customer_id,
            trace_id=uuid.uuid4(),
            actor_id="user:writer",
            event_type="test.append_only.v1",
            safe_metadata={},
        )
        event_id = event.id

    for statement, operation in (
        (text("UPDATE audit_events SET actor_id = 'user:impostor' WHERE id = :id"), "UPDATE"),
        (text("DELETE FROM audit_events WHERE id = :id"), "DELETE"),
    ):
        async with tenant_scoped_session(customer_id) as session:
            with pytest.raises(DBAPIError) as excinfo:
                await session.execute(statement, {"id": event_id})
            assert "append-only" in str(excinfo.value), f"{operation} must be refused by the trigger"

    # Still there, unchanged — the refusals were not a partial write.
    async with tenant_scoped_session(customer_id) as session:
        survivor = await session.get(AuditEvent, event_id)
        assert survivor is not None
        assert survivor.actor_id == "user:writer"
