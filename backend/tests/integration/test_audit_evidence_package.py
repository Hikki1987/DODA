"""FR-AUD-005 — "Evidence paketini eksport qilish (trace + natija + hash) —
eksport qayta tekshiriladigan hash bilan keladi."
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.application.audit_service import build_evidence_package, record_audit_event
from doda.db import tenant_scoped_session
from doda.domain.audit.models import AuditEvent
from doda.domain.base import utcnow
from doda.main import app
from tests.integration.conftest import seed_workspace_member


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_headers(session_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


async def test_package_includes_exactly_the_traced_events_with_self_consistent_hashes(
    db_available: bool,
) -> None:
    customer_id = uuid.uuid4()
    traced_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        await record_audit_event(
            session, customer_id=customer_id, trace_id=traced_id, actor_id="user:writer", event_type="a.v1"
        )
        await record_audit_event(
            session, customer_id=customer_id, trace_id=traced_id, actor_id="user:writer", event_type="b.v1"
        )
        # A different trace, interleaved — must not leak into the package.
        await record_audit_event(
            session,
            customer_id=customer_id,
            trace_id=uuid.uuid4(),
            actor_id="user:writer",
            event_type="unrelated.v1",
        )

    async with tenant_scoped_session(customer_id) as session:
        package = await build_evidence_package(session, customer_id=customer_id, trace_id=traced_id)

    assert [e.event_type for e in package.events] == ["a.v1", "b.v1"]
    assert all(e.hash_self_consistent for e in package.events)
    assert package.full_chain_verification.ok


async def test_a_tampered_events_hash_is_flagged_not_self_consistent(db_available: bool) -> None:
    """The realistic tamper vector (same as test_audit_chain_verification.py):
    a rogue direct INSERT that bypasses record_audit_event — the append-
    only trigger has no opinion on INSERT, only hash recomputation does."""
    customer_id = uuid.uuid4()
    traced_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        await record_audit_event(
            session, customer_id=customer_id, trace_id=traced_id, actor_id="user:writer", event_type="a.v1"
        )
        forged = AuditEvent(
            customer_id=customer_id,
            trace_id=traced_id,
            actor_id="user:attacker",
            event_type="forged.v1",
            occurred_at=utcnow(),
            safe_metadata={},
            prev_hash="doesn't matter for this check",
            hash="0" * 64,
        )
        session.add(forged)
        await session.flush()

    async with tenant_scoped_session(customer_id) as session:
        package = await build_evidence_package(session, customer_id=customer_id, trace_id=traced_id)

    by_type = {e.event_type: e for e in package.events}
    assert by_type["a.v1"].hash_self_consistent is True
    assert by_type["forged.v1"].hash_self_consistent is False
    # The whole-customer chain check must independently catch this too —
    # it's the OTHER integrity claim the package bundles (see
    # EvidencePackage's own docstring on why the two are not the same
    # thing).
    assert not package.full_chain_verification.ok


async def test_evidence_package_endpoint_is_scoped_to_the_requested_trace_and_is_itself_audited(
    client: AsyncClient, db_available: bool
) -> None:
    admin = await seed_workspace_member(workspace_role="workspace_admin", customer_role="customer_owner")
    traced = str(uuid.uuid4())

    proposed = await client.post(
        f"/v1/workspaces/{admin.workspace_id}/actions",
        json={"tool_name": "knowledge.read", "risk_level": "R1", "payload": {}},
        headers={
            **_auth_headers(admin.session_id),
            "Idempotency-Key": "evidence-package-1",
            "X-Trace-Id": traced,
        },
    )
    assert proposed.status_code == 200

    response = await client.get(
        f"/v1/customers/{admin.customer_id}/audit/evidence-package",
        params={"trace_id": traced},
        headers=_auth_headers(admin.session_id),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["trace_id"] == traced
    assert body["events"]
    assert all(e["hash_self_consistent"] for e in body["events"])
    assert body["full_chain_verification"]["ok"] is True

    audit = await client.get(
        f"/v1/customers/{admin.customer_id}/audit", headers=_auth_headers(admin.session_id)
    )
    event_types = [e["event_type"] for e in audit.json()]
    assert "audit.evidence_exported.v1" in event_types


async def test_plain_member_cannot_export_an_evidence_package(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member()

    response = await client.get(
        f"/v1/customers/{member.customer_id}/audit/evidence-package",
        params={"trace_id": str(uuid.uuid4())},
        headers=_auth_headers(member.session_id),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"
