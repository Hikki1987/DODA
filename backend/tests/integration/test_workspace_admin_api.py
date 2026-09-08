"""HTTP tests for workspace membership + archive/restore (FR-WKS-003/005/006)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.application.customer_service import invite_customer_member
from doda.db import tenant_scoped_session
from doda.domain.identity.models import AuthStrength
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


async def _invite_bare_customer_member(customer_id: uuid.UUID):
    """A user with a CustomerMembership but NO WorkspaceMembership yet —
    the shape add_workspace_member expects to promote into a workspace."""
    async with tenant_scoped_session(customer_id) as session:
        membership = await invite_customer_member(
            session,
            customer_id=customer_id,
            user_id=uuid.uuid4(),
            role=CustomerRole.MEMBER,
            actor_id="user:test-setup",
        )
        return membership.id


async def test_plain_member_cannot_manage_workspace_members(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member(workspace_role="member")
    candidate_id = await _invite_bare_customer_member(member.customer_id)

    response = await client.post(
        f"/v1/workspaces/{member.workspace_id}/members",
        json={"customer_membership_id": str(candidate_id), "role": "member"},
        headers=_auth_headers(member.session_id),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"


async def test_workspace_admin_can_add_and_remove_a_member(
    client: AsyncClient, db_available: bool
) -> None:
    admin = await seed_workspace_member(workspace_role="workspace_admin")
    candidate_id = await _invite_bare_customer_member(admin.customer_id)

    add_response = await client.post(
        f"/v1/workspaces/{admin.workspace_id}/members",
        json={"customer_membership_id": str(candidate_id), "role": "member"},
        headers=_auth_headers(admin.session_id),
    )
    assert add_response.status_code == 200
    membership_id = add_response.json()["id"]

    role_response = await client.patch(
        f"/v1/workspaces/{admin.workspace_id}/members/{membership_id}",
        json={"role": "workspace_admin"},
        headers=_auth_headers(admin.session_id),
    )
    assert role_response.status_code == 200
    assert role_response.json()["role"] == "workspace_admin"

    remove_response = await client.delete(
        f"/v1/workspaces/{admin.workspace_id}/members/{membership_id}",
        headers=_auth_headers(admin.session_id),
    )
    assert remove_response.status_code == 204


async def test_adding_member_from_a_different_customer_is_not_found(
    client: AsyncClient, db_available: bool
) -> None:
    """FR-WKS-003 negative test: a customer_membership_id from a different
    tenant must not be attachable to this workspace — RLS hides it as 404,
    same DENY-shaped response as everywhere else (10.1)."""
    admin = await seed_workspace_member(workspace_role="workspace_admin")
    other = await seed_workspace_member()  # different customer entirely

    response = await client.post(
        f"/v1/workspaces/{admin.workspace_id}/members",
        json={"customer_membership_id": str(uuid.uuid4()), "role": "member"},  # not even in admin's customer
        headers=_auth_headers(admin.session_id),
    )
    assert response.status_code == 404


async def test_archive_denies_further_access_and_restore_reopens_it(
    client: AsyncClient, db_available: bool
) -> None:
    admin = await seed_workspace_member(workspace_role="workspace_admin", auth_strength=AuthStrength.AAL2)

    archive_response = await client.post(
        f"/v1/workspaces/{admin.workspace_id}/archive", headers=_auth_headers(admin.session_id)
    )
    assert archive_response.status_code == 200
    assert archive_response.json()["archived_at"] is not None

    denied = await client.post(
        f"/v1/workspaces/{admin.workspace_id}/tasks",
        json={"title": "should be blocked"},
        headers=_auth_headers(admin.session_id),
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "DENY"

    restore_response = await client.post(
        f"/v1/workspaces/{admin.workspace_id}/restore", headers=_auth_headers(admin.session_id)
    )
    assert restore_response.status_code == 200
    assert restore_response.json()["archived_at"] is None

    allowed = await client.post(
        f"/v1/workspaces/{admin.workspace_id}/tasks",
        json={"title": "should work again"},
        headers=_auth_headers(admin.session_id),
    )
    assert allowed.status_code == 200


async def test_plain_member_cannot_archive_workspace(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member(workspace_role="member")
    response = await client.post(
        f"/v1/workspaces/{member.workspace_id}/archive", headers=_auth_headers(member.session_id)
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"


async def test_customer_owner_can_archive_and_manage_members_without_workspace_admin_role(
    client: AsyncClient, db_available: bool
) -> None:
    """The CustomerRole.CUSTOMER_OWNER fix, exercised over real HTTP: a
    customer_owner with NO WorkspaceMembership at all in this workspace
    must still be able to manage members and archive it (10.2: CustomerOwner
    = 'Ha' for role assignment, and the same pattern for workspace
    lifecycle) — previously only WorkspaceRole.WORKSPACE_ADMIN passed."""
    from doda.application.customer_service import create_customer_with_owner
    from doda.application.session_service import create_session
    from doda.application.workspace_service import create_workspace
    from doda.domain.identity.models import User

    owner_user_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        session.add(User(id=owner_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Owner"))
        await session.flush()
        await create_customer_with_owner(
            session, customer_id=customer_id, name="Acme", owner_user_id=owner_user_id, actor_id="user:setup"
        )
        workspace = await create_workspace(session, customer_id=customer_id, name="Main")
        owner_session = await create_session(session, user_id=owner_user_id, auth_strength=AuthStrength.AAL1)

    candidate_id = await _invite_bare_customer_member(customer_id)

    add_response = await client.post(
        f"/v1/workspaces/{workspace.id}/members",
        json={"customer_membership_id": str(candidate_id), "role": "member"},
        headers=_auth_headers(owner_session.id),
    )
    assert add_response.status_code == 200

    archive_response = await client.post(
        f"/v1/workspaces/{workspace.id}/archive", headers=_auth_headers(owner_session.id)
    )
    assert archive_response.status_code == 200
    assert archive_response.json()["archived_at"] is not None
