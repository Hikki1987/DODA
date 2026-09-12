"""The per-record tenancy guards on the single-id endpoints, for the one case
RLS does not cover: two workspaces under the SAME customer.

Every such handler checks the record twice — `record is None or
record.<scope>_id != ctx.<scope>_id` — and coverage showed not one of those
lines had ever been executed. Cross-CUSTOMER access is already stopped one
layer down (the tenant-scoped session's FORCE ROW LEVEL SECURITY makes the
row invisible, so the `is None` half fires), but RLS keys on customer_id
alone: within one customer, the explicit `!= workspace_id` comparison is the
only thing standing between a member of workspace A and a record in
workspace B. That is the same distinction the parent_task_id fix turned on
(see CLAUDE.md), so it gets tests of its own here.

Each test asserts 404 specifically: "not found" is also the right answer for
"exists but isn't yours" (10.1 — do not leak existence), and a raw 500 from
an unguarded lookup would itself be an existence oracle.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.application.session_service import create_session
from doda.application.workspace_service import create_workspace
from doda.db import tenant_scoped_session
from doda.domain.customer.models import Customer, CustomerMembership
from doda.domain.identity.models import AuthStrength, User
from doda.domain.workspace.models import WorkspaceMembership
from doda.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_headers(session_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


async def _seed_two_workspaces_one_customer():
    """One customer, two workspaces, two users — each a member of one
    workspace only. The shape RLS cannot separate, since both rows carry the
    same customer_id."""
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as db:
        user_a = User(oidc_subject_hash=str(uuid.uuid4()), display_name="A")
        user_b = User(oidc_subject_hash=str(uuid.uuid4()), display_name="B")
        db.add_all([user_a, user_b])
        await db.flush()

        db.add(Customer(id=customer_id, name="Shared Customer"))
        await db.flush()

        membership_a = CustomerMembership(customer_id=customer_id, user_id=user_a.id, role="member")
        membership_b = CustomerMembership(customer_id=customer_id, user_id=user_b.id, role="member")
        db.add_all([membership_a, membership_b])
        await db.flush()

        workspace_a = await create_workspace(db, customer_id=customer_id, name="A")
        workspace_b = await create_workspace(db, customer_id=customer_id, name="B")
        db.add_all(
            [
                WorkspaceMembership(
                    customer_id=customer_id,
                    customer_membership_id=membership_a.id,
                    workspace_id=workspace_a.id,
                    role="workspace_admin",
                ),
                WorkspaceMembership(
                    customer_id=customer_id,
                    customer_membership_id=membership_b.id,
                    workspace_id=workspace_b.id,
                    role="workspace_admin",
                ),
            ]
        )
        await db.flush()

        # A gets AAL2 deliberately: the sibling-approval test below must be
        # held up by the workspace guard itself, not by the step-up check
        # firing first and making the assertion pass for the wrong reason.
        session_a = await create_session(db, user_id=user_a.id, auth_strength=AuthStrength.AAL2)
        session_b = await create_session(db, user_id=user_b.id, auth_strength=AuthStrength.AAL1)

        return {
            "workspace_a": workspace_a.id,
            "workspace_b": workspace_b.id,
            "session_a": session_a.id,
            "session_b": session_b.id,
            "customer_id": customer_id,
            "customer_membership_a": membership_a.id,
        }


async def test_a_task_from_a_sibling_workspace_is_not_readable(
    client: AsyncClient, db_available: bool
) -> None:
    seeded = await _seed_two_workspaces_one_customer()

    created = await client.post(
        f"/v1/workspaces/{seeded['workspace_b']}/tasks",
        json={"title": "B's task"},
        headers=_auth_headers(seeded["session_b"]),
    )
    assert created.status_code == 200
    task_id = created.json()["id"]

    # A is a workspace_admin — of workspace A. Asking for B's task id through
    # A's own workspace must not resolve it.
    response = await client.get(
        f"/v1/workspaces/{seeded['workspace_a']}/tasks/{task_id}",
        headers=_auth_headers(seeded["session_a"]),
    )
    assert response.status_code == 404


async def test_a_task_status_transition_cannot_be_aimed_at_a_sibling_workspaces_task(
    client: AsyncClient, db_available: bool
) -> None:
    """The write path through the same guard — a 404 read with a working
    write would be the worse half of the two."""
    seeded = await _seed_two_workspaces_one_customer()

    created = await client.post(
        f"/v1/workspaces/{seeded['workspace_b']}/tasks",
        json={"title": "B's task"},
        headers=_auth_headers(seeded["session_b"]),
    )
    task_id = created.json()["id"]

    response = await client.post(
        f"/v1/workspaces/{seeded['workspace_a']}/tasks/{task_id}/status",
        json={"target_status": "IN_PROGRESS"},
        headers=_auth_headers(seeded["session_a"]),
    )
    assert response.status_code == 404

    # And it really did not happen, rather than 404-ing after the write.
    still_todo = await client.get(
        f"/v1/workspaces/{seeded['workspace_b']}/tasks/{task_id}",
        headers=_auth_headers(seeded["session_b"]),
    )
    assert still_todo.json()["status"] == "TODO"


async def test_a_sibling_workspaces_membership_cannot_be_managed(
    client: AsyncClient, db_available: bool
) -> None:
    """FR-WKS-003 via the _get_workspace_membership guard: a workspace_admin
    of A holding B's membership id must not be able to re-role or remove it,
    even though both rows are in the same customer and so both visible to
    RLS."""
    seeded = await _seed_two_workspaces_one_customer()
    members_of_b = await client.get(
        f"/v1/workspaces/{seeded['workspace_b']}/members", headers=_auth_headers(seeded["session_b"])
    )
    membership_id = members_of_b.json()[0]["membership_id"]

    patched = await client.patch(
        f"/v1/workspaces/{seeded['workspace_a']}/members/{membership_id}",
        json={"role": "member"},
        headers=_auth_headers(seeded["session_a"]),
    )
    assert patched.status_code == 404

    deleted = await client.delete(
        f"/v1/workspaces/{seeded['workspace_a']}/members/{membership_id}",
        headers=_auth_headers(seeded["session_a"]),
    )
    assert deleted.status_code == 404


async def test_another_members_notification_cannot_be_marked_read(
    client: AsyncClient, db_available: bool
) -> None:
    """Not a workspace-scope check but the same class of per-record guard
    (`recipient_id != this user`), and likewise never exercised. So this one
    puts BOTH users in the same workspace — otherwise the authz chain would
    reject the request long before the guard is reached, and the test would
    prove the wrong layer."""
    seeded = await _seed_two_workspaces_one_customer()
    async with tenant_scoped_session(seeded["customer_id"]) as db:
        db.add(
            WorkspaceMembership(
                customer_id=seeded["customer_id"],
                customer_membership_id=seeded["customer_membership_a"],
                workspace_id=seeded["workspace_b"],
                role="member",
            )
        )
        await db.flush()

    # A COMPLETED_TASK notification addressed to B, raised by B's own work.
    created = await client.post(
        f"/v1/workspaces/{seeded['workspace_b']}/tasks",
        json={"title": "B's task"},
        headers=_auth_headers(seeded["session_b"]),
    )
    task_id = created.json()["id"]
    for status in ("IN_PROGRESS", "DONE"):
        await client.post(
            f"/v1/workspaces/{seeded['workspace_b']}/tasks/{task_id}/status",
            json={"target_status": status},
            headers=_auth_headers(seeded["session_b"]),
        )
    listed = await client.get(
        f"/v1/workspaces/{seeded['workspace_b']}/notifications",
        headers=_auth_headers(seeded["session_b"]),
    )
    notification_id = listed.json()[0]["id"]

    response = await client.post(
        f"/v1/workspaces/{seeded['workspace_b']}/notifications/{notification_id}/read",
        headers=_auth_headers(seeded["session_a"]),
    )
    assert response.status_code == 404

    unread_for_b = await client.get(
        f"/v1/workspaces/{seeded['workspace_b']}/notifications",
        headers=_auth_headers(seeded["session_b"]),
    )
    assert unread_for_b.json()[0]["read_at"] is None


async def test_a_single_action_read_is_scoped_to_its_own_workspace(
    client: AsyncClient, db_available: bool
) -> None:
    """GET /v1/workspaces/{id}/actions/{action_id} had no coverage at all —
    not even its happy path — so both halves are asserted here: the owning
    workspace resolves the action, a sibling workspace 404s on the same id."""
    seeded = await _seed_two_workspaces_one_customer()

    proposed = await client.post(
        f"/v1/workspaces/{seeded['workspace_b']}/actions",
        json={"tool_name": "knowledge.read", "risk_level": "R1", "payload": {}},
        headers={**_auth_headers(seeded["session_b"]), "Idempotency-Key": f"single-read-{uuid.uuid4()}"},
    )
    assert proposed.status_code == 200
    action_id = proposed.json()["action"]["id"]

    own = await client.get(
        f"/v1/workspaces/{seeded['workspace_b']}/actions/{action_id}",
        headers=_auth_headers(seeded["session_b"]),
    )
    assert own.status_code == 200
    assert own.json()["id"] == action_id

    sibling = await client.get(
        f"/v1/workspaces/{seeded['workspace_a']}/actions/{action_id}",
        headers=_auth_headers(seeded["session_a"]),
    )
    assert sibling.status_code == 404


async def test_an_approval_cannot_be_consumed_through_a_sibling_workspace(
    client: AsyncClient, db_available: bool
) -> None:
    """The nastier of the two guards on the consume endpoint: the Approval row
    passes its own customer_id check (same customer!), so only the second
    check — the action's workspace — stops a member of A from consuming a
    one-time approval nonce belonging to workspace B. 9.2's nonce is exactly
    the thing that must not be spendable by the wrong caller."""
    seeded = await _seed_two_workspaces_one_customer()

    proposed = await client.post(
        f"/v1/workspaces/{seeded['workspace_b']}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "b@example.com"}},
        headers={**_auth_headers(seeded["session_b"]), "Idempotency-Key": f"sibling-nonce-{uuid.uuid4()}"},
    )
    body = proposed.json()
    assert body["action"]["status"] == "AWAITING_APPROVAL"
    approval_id, nonce = body["approval"]["id"], body["approval"]["nonce"]

    response = await client.post(
        f"/v1/workspaces/{seeded['workspace_a']}/approvals/{approval_id}/consume",
        json={"nonce": nonce},
        headers=_auth_headers(seeded["session_a"]),
    )
    assert response.status_code == 404

    # The nonce is still unspent: B can still use it themselves.
    still_pending = await client.get(
        f"/v1/workspaces/{seeded['workspace_b']}/actions/{body['action']['id']}",
        headers=_auth_headers(seeded["session_b"]),
    )
    assert still_pending.json()["status"] == "AWAITING_APPROVAL"
