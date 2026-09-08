"""End-to-end HTTP tests for the task API — same authoritative-chain
pattern as test_actions_api.py (Session -> Workspace Membership -> RBAC)."""

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


def _auth_headers(session_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


async def test_missing_session_is_rejected(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()
    response = await client.post(
        f"/v1/workspaces/{member.workspace_id}/tasks", json={"title": "Write report"}
    )
    assert response.status_code == 401


async def test_no_membership_is_denied(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()
    other = await seed_workspace_member()
    response = await client.post(
        f"/v1/workspaces/{other.workspace_id}/tasks",
        json={"title": "Write report"},
        headers=_auth_headers(member.session_id),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"


async def test_member_can_create_and_read_own_task(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()

    create = await client.post(
        f"/v1/workspaces/{member.workspace_id}/tasks",
        json={"title": "Write report"},
        headers=_auth_headers(member.session_id),
    )
    assert create.status_code == 200
    task = create.json()
    assert task["status"] == "TODO"
    assert task["owner_id"] == f"user:{member.user_id}"

    get_response = await client.get(
        f"/v1/workspaces/{member.workspace_id}/tasks/{task['id']}",
        headers=_auth_headers(member.session_id),
    )
    assert get_response.status_code == 200


async def test_owner_can_advance_task_status(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()
    create = await client.post(
        f"/v1/workspaces/{member.workspace_id}/tasks",
        json={"title": "Write report"},
        headers=_auth_headers(member.session_id),
    )
    task_id = create.json()["id"]

    response = await client.post(
        f"/v1/workspaces/{member.workspace_id}/tasks/{task_id}/status",
        json={"target_status": "IN_PROGRESS"},
        headers=_auth_headers(member.session_id),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "IN_PROGRESS"


async def test_invalid_transition_is_rejected(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()
    create = await client.post(
        f"/v1/workspaces/{member.workspace_id}/tasks",
        json={"title": "Write report"},
        headers=_auth_headers(member.session_id),
    )
    task_id = create.json()["id"]

    response = await client.post(
        f"/v1/workspaces/{member.workspace_id}/tasks/{task_id}/status",
        json={"target_status": "DONE"},  # skips IN_PROGRESS
        headers=_auth_headers(member.session_id),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_STATE"


async def test_non_owner_member_cannot_change_someone_elses_task(
    client: AsyncClient, db_available: bool
) -> None:
    """FR-TASK-004 negative test: an authenticated, workspace-member
    caller who is neither the task owner nor a workspace_admin must be
    denied, not silently allowed because they hold *some* valid session."""
    import doda.db as doda_db
    from doda.application.session_service import create_session
    from doda.application.workspace_service import create_workspace
    from doda.domain.customer.models import Customer, CustomerMembership
    from doda.domain.identity.models import User
    from doda.domain.workspace.models import WorkspaceMembership

    customer_id = uuid.uuid4()
    async with doda_db.tenant_scoped_session(customer_id) as db:
        owner = User(oidc_subject_hash=str(uuid.uuid4()), display_name="Owner")
        bystander = User(oidc_subject_hash=str(uuid.uuid4()), display_name="Bystander")
        db.add_all([owner, bystander])
        await db.flush()

        db.add(Customer(id=customer_id, name="Shared Customer"))
        await db.flush()

        owner_membership = CustomerMembership(customer_id=customer_id, user_id=owner.id, role="member")
        bystander_membership = CustomerMembership(
            customer_id=customer_id, user_id=bystander.id, role="member"
        )
        db.add_all([owner_membership, bystander_membership])
        await db.flush()

        workspace = await create_workspace(db, customer_id=customer_id, name="Shared Workspace")

        db.add_all(
            [
                WorkspaceMembership(
                    customer_id=customer_id,
                    customer_membership_id=owner_membership.id,
                    workspace_id=workspace.id,
                    role="member",
                ),
                WorkspaceMembership(
                    customer_id=customer_id,
                    customer_membership_id=bystander_membership.id,
                    workspace_id=workspace.id,
                    role="member",
                ),
            ]
        )
        await db.flush()

        owner_session = await create_session(db, user_id=owner.id, auth_strength=AuthStrength.AAL1)
        bystander_session = await create_session(db, user_id=bystander.id, auth_strength=AuthStrength.AAL1)

    create = await client.post(
        f"/v1/workspaces/{workspace.id}/tasks",
        json={"title": "Owner's task"},
        headers=_auth_headers(owner_session.id),
    )
    task_id = create.json()["id"]

    response = await client.post(
        f"/v1/workspaces/{workspace.id}/tasks/{task_id}/status",
        json={"target_status": "IN_PROGRESS"},
        headers=_auth_headers(bystander_session.id),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"


async def test_task_history_records_creation_and_transition(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()
    create = await client.post(
        f"/v1/workspaces/{member.workspace_id}/tasks",
        json={"title": "Write report"},
        headers=_auth_headers(member.session_id),
    )
    task_id = create.json()["id"]

    await client.post(
        f"/v1/workspaces/{member.workspace_id}/tasks/{task_id}/status",
        json={"target_status": "IN_PROGRESS"},
        headers=_auth_headers(member.session_id),
    )

    history = await client.get(
        f"/v1/workspaces/{member.workspace_id}/tasks/{task_id}/history",
        headers=_auth_headers(member.session_id),
    )
    assert history.status_code == 200
    entries = history.json()
    assert [e["to_status"] for e in entries] == ["TODO", "IN_PROGRESS"]
    assert entries[0]["from_status"] is None
    assert entries[1]["from_status"] == "TODO"
