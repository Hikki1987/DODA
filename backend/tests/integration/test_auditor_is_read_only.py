"""10.2's Auditor row is "read-only" — this file holds it to that over real
HTTP, for the workspace-scoped write paths specifically.

Why this needs its own file: the only place CustomerRole.AUDITOR was ever
checked is authorize_view_customer_audit (customer-scoped). Every
workspace-scoped authorize_* function looks at WorkspaceRole alone, and
WorkspaceRole has no read-only member — domain/security/roles.py says so
outright ("CustomerRole.AUDITOR has no WorkspaceRole counterpart by
design (auditors are read-only, 2.2)"). So the invariant rests entirely on
an auditor never resolving to a WorkspaceRole at all, which is exactly what
these tests pin down.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.application.customer_service import invite_customer_member
from doda.db import tenant_scoped_session
from doda.domain.security.roles import CustomerRole
from doda.main import app
from tests.integration.conftest import seed_workspace_member


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_headers(session_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


async def test_an_auditor_with_a_workspace_membership_cannot_create_a_task(
    client: AsyncClient, db_available: bool
) -> None:
    """The scenario a customer owner would actually produce: grant an outside
    compliance reviewer the read-only `auditor` customer role, then add them
    to a workspace so they can see it. Nothing about that should hand them
    write authority."""
    auditor = await seed_workspace_member(customer_role="auditor")

    response = await client.post(
        f"/v1/workspaces/{auditor.workspace_id}/tasks",
        json={"title": "Auditor should not be able to write this"},
        headers=_auth_headers(auditor.session_id),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"


async def test_an_auditor_with_a_workspace_membership_cannot_propose_an_action(
    client: AsyncClient, db_available: bool
) -> None:
    auditor = await seed_workspace_member(customer_role="auditor")

    response = await client.post(
        f"/v1/workspaces/{auditor.workspace_id}/actions",
        json={"tool_name": "knowledge.read", "risk_level": "R1", "payload": {"query": "hi"}},
        headers={
            **_auth_headers(auditor.session_id),
            "Idempotency-Key": "auditor-propose-1",
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"


async def test_an_auditor_made_workspace_admin_still_cannot_engage_the_kill_switch(
    client: AsyncClient, db_available: bool
) -> None:
    """Worse shape of the same mistake: the owner adds the auditor with the
    `workspace_admin` workspace role. Customer-level read-only must still
    win — 10.2's Auditor row has no write cell anywhere."""
    auditor = await seed_workspace_member(customer_role="auditor", workspace_role="workspace_admin")

    response = await client.post(
        f"/v1/workspaces/{auditor.workspace_id}/kill-switch/engage",
        json={"reason": "auditor should not be able to do this"},
        headers=_auth_headers(auditor.session_id),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"


async def test_adding_an_auditor_to_a_workspace_is_refused_outright(
    client: AsyncClient, db_available: bool
) -> None:
    """Second layer, at the source: the powerless membership row is never
    created, so the members list can't show an auditor holding a workspace
    role that get_workspace_context will refuse to honour anyway.

    Also the first coverage of WorkspaceMembershipError's HTTP envelope
    (409 MEMBERSHIP_INVALID) — the exception had service-level tests only.
    """
    admin = await seed_workspace_member(workspace_role="workspace_admin")

    async with tenant_scoped_session(admin.customer_id) as session:
        auditor_membership = await invite_customer_member(
            session,
            customer_id=admin.customer_id,
            user_id=uuid.uuid4(),
            role=CustomerRole.AUDITOR,
            actor_id="user:test-setup",
        )
        auditor_membership_id = auditor_membership.id

    response = await client.post(
        f"/v1/workspaces/{admin.workspace_id}/members",
        json={"customer_membership_id": str(auditor_membership_id), "role": "member"},
        headers=_auth_headers(admin.session_id),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "MEMBERSHIP_INVALID"
