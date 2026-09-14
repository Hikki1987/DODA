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


async def test_parent_task_id_from_another_workspace_in_the_same_customer_is_rejected(
    client: AsyncClient, db_available: bool
) -> None:
    """Security regression: create_task used to insert parent_task_id with
    only a DB-level FK backing it, no application-level check that the
    referenced task is in the caller's own workspace. A cross-CUSTOMER
    reference already fails on its own here — FORCE ROW LEVEL SECURITY
    applies to the FK check too when the acting role isn't a Postgres
    superuser (this project's own doda_app role deliberately isn't, see
    the RLS-bypass fix elsewhere in CLAUDE.md) — but RLS is scoped by
    customer_id only, so a task in a DIFFERENT WORKSPACE under the SAME
    customer was still FK-visible and would satisfy the constraint,
    letting one workspace's task silently become another's parent, or
    (for a genuinely nonexistent UUID) raising an unhandled 500 — a
    200-vs-500 existence oracle. Fixed by looking the parent up in the
    caller's own workspace first."""
    import doda.db as doda_db
    from doda.application.session_service import create_session
    from doda.application.workspace_service import create_workspace
    from doda.domain.customer.models import Customer, CustomerMembership
    from doda.domain.identity.models import User
    from doda.domain.workspace.models import WorkspaceMembership

    customer_id = uuid.uuid4()
    async with doda_db.tenant_scoped_session(customer_id) as db:
        user = User(oidc_subject_hash=str(uuid.uuid4()), display_name="Multi-workspace user")
        db.add(user)
        await db.flush()

        db.add(Customer(id=customer_id, name="Shared Customer"))
        await db.flush()

        membership = CustomerMembership(customer_id=customer_id, user_id=user.id, role="member")
        db.add(membership)
        await db.flush()

        workspace_a = await create_workspace(db, customer_id=customer_id, name="A")
        workspace_b = await create_workspace(db, customer_id=customer_id, name="B")
        db.add_all(
            [
                WorkspaceMembership(
                    customer_id=customer_id,
                    customer_membership_id=membership.id,
                    workspace_id=workspace_a.id,
                    role="member",
                ),
                WorkspaceMembership(
                    customer_id=customer_id,
                    customer_membership_id=membership.id,
                    workspace_id=workspace_b.id,
                    role="member",
                ),
            ]
        )
        await db.flush()
        session_record = await create_session(db, user_id=user.id, auth_strength=AuthStrength.AAL1)

    session_headers = _auth_headers(session_record.id)

    task_in_b = await client.post(
        f"/v1/workspaces/{workspace_b.id}/tasks", json={"title": "Task in B"}, headers=session_headers
    )
    task_in_b_id = task_in_b.json()["id"]

    response = await client.post(
        f"/v1/workspaces/{workspace_a.id}/tasks",
        json={"title": "Mine, in A", "parent_task_id": task_in_b_id},
        headers=session_headers,
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_parent_task_id_within_the_same_workspace_succeeds(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member()

    parent = await client.post(
        f"/v1/workspaces/{member.workspace_id}/tasks",
        json={"title": "Parent"},
        headers=_auth_headers(member.session_id),
    )
    parent_id = parent.json()["id"]

    child = await client.post(
        f"/v1/workspaces/{member.workspace_id}/tasks",
        json={"title": "Child", "parent_task_id": parent_id},
        headers=_auth_headers(member.session_id),
    )
    assert child.status_code == 200
    assert child.json()["parent_task_id"] == parent_id


async def test_nonexistent_parent_task_id_is_404_not_500(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()

    response = await client.post(
        f"/v1/workspaces/{member.workspace_id}/tasks",
        json={"title": "Orphan", "parent_task_id": str(uuid.uuid4())},
        headers=_auth_headers(member.session_id),
    )
    assert response.status_code == 404


async def test_list_workspace_tasks_returns_all_tasks_in_the_workspace(
    client: AsyncClient, db_available: bool
) -> None:
    """There was no way to list tasks in a workspace at all before this —
    only create and get-by-id — the same class of discoverability gap
    GET /v1/me/workspaces closed one level up."""
    member = await seed_workspace_member()
    for title in ("First", "Second", "Third"):
        await client.post(
            f"/v1/workspaces/{member.workspace_id}/tasks",
            json={"title": title},
            headers=_auth_headers(member.session_id),
        )

    response = await client.get(
        f"/v1/workspaces/{member.workspace_id}/tasks", headers=_auth_headers(member.session_id)
    )
    assert response.status_code == 200
    assert {task["title"] for task in response.json()} == {"First", "Second", "Third"}


async def test_list_workspace_tasks_filters_by_status(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()
    done = await client.post(
        f"/v1/workspaces/{member.workspace_id}/tasks",
        json={"title": "Done one"},
        headers=_auth_headers(member.session_id),
    )
    await client.post(
        f"/v1/workspaces/{member.workspace_id}/tasks",
        json={"title": "Still todo"},
        headers=_auth_headers(member.session_id),
    )
    await client.post(
        f"/v1/workspaces/{member.workspace_id}/tasks/{done.json()['id']}/status",
        json={"target_status": "IN_PROGRESS"},
        headers=_auth_headers(member.session_id),
    )
    await client.post(
        f"/v1/workspaces/{member.workspace_id}/tasks/{done.json()['id']}/status",
        json={"target_status": "DONE"},
        headers=_auth_headers(member.session_id),
    )

    response = await client.get(
        f"/v1/workspaces/{member.workspace_id}/tasks?status=DONE", headers=_auth_headers(member.session_id)
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["title"] == "Done one"


async def test_list_workspace_tasks_does_not_leak_another_workspaces_tasks(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member()
    other = await seed_workspace_member()
    await client.post(
        f"/v1/workspaces/{other.workspace_id}/tasks",
        json={"title": "Someone else's task"},
        headers=_auth_headers(other.session_id),
    )

    response = await client.get(
        f"/v1/workspaces/{member.workspace_id}/tasks", headers=_auth_headers(member.session_id)
    )
    assert response.status_code == 200
    assert response.json() == []
