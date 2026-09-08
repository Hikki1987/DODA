"""GET /v1/me/export — FR-CTL-002 ("ma'lumot eksporti"). Proves the export
actually aggregates the caller's own data across every customer/workspace
they belong to, and never another member's data even within a shared
workspace.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.application.customer_service import create_customer_with_owner, invite_customer_member
from doda.application.session_service import create_session
from doda.application.workspace_service import add_workspace_member, create_workspace
from doda.db import tenant_scoped_session
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


async def test_export_contains_only_the_callers_own_tasks_notifications_and_audit_events(
    client: AsyncClient, db_available: bool
) -> None:
    customer_id = uuid.uuid4()
    member_user_id = uuid.uuid4()
    other_member_user_id = uuid.uuid4()

    async with tenant_scoped_session(customer_id) as db:
        db.add_all(
            [
                User(id=member_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Exporter"),
                User(id=other_member_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Other"),
            ]
        )
        await db.flush()

        await create_customer_with_owner(
            db, customer_id=customer_id, name="Acme", owner_user_id=uuid.uuid4(), actor_id="user:setup"
        )
        member_membership = await invite_customer_member(
            db,
            customer_id=customer_id,
            user_id=member_user_id,
            role=CustomerRole.MEMBER,
            actor_id="user:setup",
        )
        other_membership = await invite_customer_member(
            db,
            customer_id=customer_id,
            user_id=other_member_user_id,
            role=CustomerRole.MEMBER,
            actor_id="user:setup",
        )
        workspace = await create_workspace(db, customer_id=customer_id, name="Shared")
        await add_workspace_member(
            db,
            workspace=workspace,
            customer_membership=member_membership,
            role="member",
            actor_id="user:setup",
        )
        await add_workspace_member(
            db,
            workspace=workspace,
            customer_membership=other_membership,
            role="member",
            actor_id="user:setup",
        )
        member_session = await create_session(db, user_id=member_user_id, auth_strength=AuthStrength.AAL1)

    member_headers = _auth_headers(member_session.id)

    # The exporting member's own task.
    my_task = await client.post(
        f"/v1/workspaces/{workspace.id}/tasks",
        json={"title": "My own task"},
        headers=member_headers,
    )
    assert my_task.status_code == 200

    # The exporting member's own R3 action -> PENDING_APPROVAL notification
    # + an action.awaiting_approval.v1 audit event with them as actor.
    action_response = await client.post(
        f"/v1/workspaces/{workspace.id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "boss@example.com"}},
        headers={**member_headers, "Idempotency-Key": "export-test-1"},
    )
    assert action_response.status_code == 200

    export_response = await client.get("/v1/me/export", headers=member_headers)
    assert export_response.status_code == 200
    body = export_response.json()

    assert body["user_id"] == str(member_user_id)
    assert any(m["workspace_id"] == str(workspace.id) for m in body["memberships"])

    assert [t["title"] for t in body["tasks"]] == ["My own task"]
    assert all(t["owner_id"] == f"user:{member_user_id}" for t in body["tasks"])

    notification_types = [n["notification_type"] for n in body["notifications"]]
    assert "PENDING_APPROVAL" in notification_types

    audit_actor_ids = {e["actor_id"] for e in body["audit_events"]}
    assert audit_actor_ids == {f"user:{member_user_id}"}  # never the other member's or owner's events
    audit_event_types = {e["event_type"] for e in body["audit_events"]}
    assert "action.proposed.v1" in audit_event_types


async def test_exporting_data_is_itself_audited(client: AsyncClient, db_available: bool) -> None:
    customer_id = uuid.uuid4()
    owner_user_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as db:
        db.add(User(id=owner_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Owner"))
        await db.flush()
        await create_customer_with_owner(
            db, customer_id=customer_id, name="Acme", owner_user_id=owner_user_id, actor_id="user:setup"
        )
        owner_session = await create_session(db, user_id=owner_user_id, auth_strength=AuthStrength.AAL1)

    export_response = await client.get("/v1/me/export", headers=_auth_headers(owner_session.id))
    assert export_response.status_code == 200

    audit_response = await client.get(
        f"/v1/customers/{customer_id}/audit", headers=_auth_headers(owner_session.id)
    )
    event_types = [e["event_type"] for e in audit_response.json()]
    assert "user.data_exported.v1" in event_types
