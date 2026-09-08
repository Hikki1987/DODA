"""FR-NTF — the customer-scoped notification inbox (api/notifications.py's
list_my_notifications_across_workspaces), closing a gap CLAUDE.md had
flagged since S2: a member of several workspaces under one customer had
no single place to see notifications from all of them.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.application.customer_service import create_customer_with_owner
from doda.application.session_service import create_session
from doda.application.workspace_service import add_workspace_member, create_workspace
from doda.db import tenant_scoped_session
from doda.domain.identity.models import AuthStrength, User
from doda.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_headers(session_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


async def _seed_member_of_two_workspaces(customer_id: uuid.UUID):
    """One real Identity User, a member of TWO workspaces under the SAME
    customer — the exact shape the old workspace-scoped-only endpoint
    could never show in one call."""
    user_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        session.add(
            User(id=user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Multi-workspace user")
        )
        await session.flush()

        _customer, owner_membership = await create_customer_with_owner(
            session, customer_id=customer_id, name="Acme", owner_user_id=user_id, actor_id="user:setup"
        )
        workspace_a = await create_workspace(session, customer_id=customer_id, name="A")
        workspace_b = await create_workspace(session, customer_id=customer_id, name="B")
        await add_workspace_member(
            session,
            workspace=workspace_a,
            customer_membership=owner_membership,
            role="member",
            actor_id="user:setup",
        )
        await add_workspace_member(
            session,
            workspace=workspace_b,
            customer_membership=owner_membership,
            role="member",
            actor_id="user:setup",
        )
        session_record = await create_session(session, user_id=user_id, auth_strength=AuthStrength.AAL1)

    return user_id, session_record.id, workspace_a.id, workspace_b.id


async def test_customer_inbox_shows_notifications_from_every_workspace(
    client: AsyncClient, db_available: bool
) -> None:
    customer_id = uuid.uuid4()
    user_id, session_id, workspace_a_id, workspace_b_id = await _seed_member_of_two_workspaces(customer_id)

    # An R3 proposal fires a real PENDING_APPROVAL notification (see
    # test_notifications.py) — trigger one in each workspace.
    for workspace_id, key in [(workspace_a_id, "inbox-a"), (workspace_b_id, "inbox-b")]:
        submit = await client.post(
            f"/v1/workspaces/{workspace_id}/actions",
            json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "x@example.com"}},
            headers={**_auth_headers(session_id), "Idempotency-Key": key},
        )
        assert submit.status_code == 200

    response = await client.get(
        f"/v1/customers/{customer_id}/notifications", headers=_auth_headers(session_id)
    )
    assert response.status_code == 200
    body = response.json()
    seen_workspace_ids = {n["workspace_id"] for n in body}
    assert seen_workspace_ids == {str(workspace_a_id), str(workspace_b_id)}


async def test_customer_inbox_denies_a_user_with_no_customer_membership(
    client: AsyncClient, db_available: bool
) -> None:
    customer_id = uuid.uuid4()
    await _seed_member_of_two_workspaces(customer_id)

    outsider_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        session.add(User(id=outsider_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Outsider"))
        await session.flush()
        outsider_session = await create_session(session, user_id=outsider_id, auth_strength=AuthStrength.AAL1)

    response = await client.get(
        f"/v1/customers/{customer_id}/notifications", headers=_auth_headers(outsider_session.id)
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"


async def test_mark_read_via_customer_scoped_endpoint(client: AsyncClient, db_available: bool) -> None:
    customer_id = uuid.uuid4()
    _user_id, session_id, workspace_a_id, _workspace_b_id = await _seed_member_of_two_workspaces(customer_id)

    # An R3 proposal fires a real PENDING_APPROVAL notification — the
    # simplest real trigger available (see test_notifications.py).
    submit = await client.post(
        f"/v1/workspaces/{workspace_a_id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "x@example.com"}},
        headers={**_auth_headers(session_id), "Idempotency-Key": "inbox-mark-read-2"},
    )
    assert submit.status_code == 200

    listed = await client.get(f"/v1/customers/{customer_id}/notifications", headers=_auth_headers(session_id))
    notification_id = listed.json()[0]["id"]
    assert listed.json()[0]["read_at"] is None

    read_response = await client.post(
        f"/v1/customers/{customer_id}/notifications/{notification_id}/read",
        headers=_auth_headers(session_id),
    )
    assert read_response.status_code == 200
    assert read_response.json()["read_at"] is not None
