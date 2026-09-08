"""End-to-end HTTP tests for the action API — proves the authoritative
chain (section 10) actually gates the endpoints, not just that the
application-layer functions do when called directly (test_action_lifecycle.py
already covers that). Every test here goes through real HTTP + a real
Postgres-backed Session/Membership chain.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.domain.identity.models import AuthStrength
from doda.main import app
from tests.integration.conftest import seed_workspace_member


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_headers(session_id: uuid.UUID, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {session_id}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


async def test_missing_session_is_rejected(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()
    response = await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "knowledge.read", "risk_level": "R1", "payload": {}},
        headers={"Idempotency-Key": "no-auth-1"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_session_with_no_membership_is_denied(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()
    other_workspace = await seed_workspace_member()  # different customer/workspace entirely

    response = await client.post(
        f"/v1/workspaces/{other_workspace.workspace_id}/actions",
        json={"tool_name": "knowledge.read", "risk_level": "R1", "payload": {}},
        headers=_auth_headers(member.session_id, "no-membership-1"),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"


async def test_low_risk_action_is_auto_ready_end_to_end(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()

    response = await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "knowledge.read", "risk_level": "R1", "payload": {"query": "hi"}},
        headers=_auth_headers(member.session_id, "e2e-r1-1"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["action"]["status"] == "READY"
    assert body["approval"] is None


async def test_duplicate_idempotency_key_returns_same_action(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()
    payload = {"tool_name": "knowledge.read", "risk_level": "R1", "payload": {"query": "hi"}}
    headers = _auth_headers(member.session_id, "e2e-idem-1")

    first = await client.post(f"/v1/workspaces/{member.workspace_id}/actions", json=payload, headers=headers)
    second = await client.post(f"/v1/workspaces/{member.workspace_id}/actions", json=payload, headers=headers)

    assert first.json()["action"]["id"] == second.json()["action"]["id"]


async def test_high_risk_action_requires_step_up_before_approval_consumption(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member(auth_strength=AuthStrength.AAL1)

    submit = await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "boss@example.com"}},
        headers=_auth_headers(member.session_id, "e2e-r3-1"),
    )
    body = submit.json()
    assert body["action"]["status"] == "AWAITING_APPROVAL"
    assert body["approval"] is not None

    consume = await client.post(
        f"/v1/workspaces/{member.workspace_id}/approvals/{body['approval']['id']}/consume",
        json={"nonce": body["approval"]["nonce"]},
        headers=_auth_headers(member.session_id),
    )
    assert consume.status_code == 403
    assert consume.json()["code"] == "STEP_UP_REQUIRED"


async def test_high_risk_action_self_approval_succeeds_with_fresh_mfa(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member(auth_strength=AuthStrength.AAL2)

    submit = await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "boss@example.com"}},
        headers=_auth_headers(member.session_id, "e2e-r3-2"),
    )
    body = submit.json()

    consume = await client.post(
        f"/v1/workspaces/{member.workspace_id}/approvals/{body['approval']['id']}/consume",
        json={"nonce": body["approval"]["nonce"]},
        headers=_auth_headers(member.session_id),
    )
    assert consume.status_code == 200
    assert consume.json()["status"] == "READY"


async def test_wrong_nonce_is_rejected_over_http(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member(auth_strength=AuthStrength.AAL2)

    submit = await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "boss@example.com"}},
        headers=_auth_headers(member.session_id, "e2e-r3-3"),
    )
    approval = submit.json()["approval"]

    consume = await client.post(
        f"/v1/workspaces/{member.workspace_id}/approvals/{approval['id']}/consume",
        json={"nonce": "wrong-nonce"},
        headers=_auth_headers(member.session_id),
    )
    assert consume.status_code == 409
    assert consume.json()["code"] == "APPROVAL_INVALID"


async def test_approval_from_another_workspace_is_not_found(client: AsyncClient, db_available: bool) -> None:
    member_a = await seed_workspace_member(auth_strength=AuthStrength.AAL2)
    member_b = await seed_workspace_member(auth_strength=AuthStrength.AAL2)

    submit = await client.post(
        f"/v1/workspaces/{member_a.workspace_id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "boss@example.com"}},
        headers=_auth_headers(member_a.session_id, "e2e-cross-1"),
    )
    approval_id = submit.json()["approval"]["id"]

    # member_b is authenticated and has real membership — just in a
    # different workspace/customer, so they pass the workspace-membership
    # gate on their own path but the approval itself belongs to a different
    # tenant. 404, not 403: existence of another tenant's approval id is
    # not something to confirm either way (10.1: sezgir tafsilot ko'rsatilmaydi).
    consume = await client.post(
        f"/v1/workspaces/{member_b.workspace_id}/approvals/{approval_id}/consume",
        json={"nonce": "irrelevant"},
        headers=_auth_headers(member_b.session_id),
    )
    assert consume.status_code == 404


async def test_workspace_admin_can_approve_a_members_action(client: AsyncClient, db_available: bool) -> None:
    # Two separate memberships in the SAME workspace: proposer (member) and
    # approver (workspace_admin). seed_workspace_member always creates a
    # fresh workspace, so build this scenario by hand instead of reusing it
    # verbatim for the second identity.
    import doda.db as doda_db
    from doda.application.session_service import create_session
    from doda.application.workspace_service import create_workspace
    from doda.domain.customer.models import Customer, CustomerMembership
    from doda.domain.identity.models import User
    from doda.domain.workspace.models import WorkspaceMembership

    customer_id = uuid.uuid4()
    async with doda_db.tenant_scoped_session(customer_id) as db:
        proposer = User(oidc_subject_hash=str(uuid.uuid4()), display_name="Proposer")
        approver = User(oidc_subject_hash=str(uuid.uuid4()), display_name="Approver")
        db.add_all([proposer, approver])
        await db.flush()

        db.add(Customer(id=customer_id, name="Shared Customer"))
        await db.flush()

        proposer_membership = CustomerMembership(customer_id=customer_id, user_id=proposer.id, role="member")
        approver_membership = CustomerMembership(customer_id=customer_id, user_id=approver.id, role="member")
        db.add_all([proposer_membership, approver_membership])
        await db.flush()

        workspace = await create_workspace(db, customer_id=customer_id, name="Shared Workspace")

        db.add_all(
            [
                WorkspaceMembership(
                    customer_id=customer_id,
                    customer_membership_id=proposer_membership.id,
                    workspace_id=workspace.id,
                    role="member",
                ),
                WorkspaceMembership(
                    customer_id=customer_id,
                    customer_membership_id=approver_membership.id,
                    workspace_id=workspace.id,
                    role="workspace_admin",
                ),
            ]
        )
        await db.flush()

        proposer_session = await create_session(db, user_id=proposer.id, auth_strength=AuthStrength.AAL1)
        approver_session = await create_session(db, user_id=approver.id, auth_strength=AuthStrength.AAL2)

    submit = await client.post(
        f"/v1/workspaces/{workspace.id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "x@example.com"}},
        headers=_auth_headers(proposer_session.id, "e2e-admin-approve-1"),
    )
    approval = submit.json()["approval"]

    consume = await client.post(
        f"/v1/workspaces/{workspace.id}/approvals/{approval['id']}/consume",
        json={"nonce": approval["nonce"]},
        headers=_auth_headers(approver_session.id),
    )
    assert consume.status_code == 200
    assert consume.json()["status"] == "READY"
