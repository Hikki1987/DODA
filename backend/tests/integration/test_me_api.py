"""GET /v1/me/workspaces — the discovery endpoint that didn't exist before
UserCustomerIndex: every other endpoint in this API requires the caller to
already know a workspace_id or customer_id, so a client had no way to find
out what it's allowed to call next after login.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.application.customer_service import (
    create_customer_with_owner,
    invite_customer_member,
    remove_customer_member,
)
from doda.application.session_service import create_session
from doda.application.workspace_service import add_workspace_member, create_workspace
from doda.db import async_session_factory, tenant_scoped_session
from doda.domain.customer.models import CustomerMembership, UserCustomerIndex
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


async def test_user_with_no_memberships_sees_an_empty_list(client: AsyncClient, db_available: bool) -> None:
    user_id = uuid.uuid4()
    async with tenant_scoped_session(uuid.uuid4()) as db:
        db.add(User(id=user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Lonely"))
        await db.flush()
        session_record = await create_session(db, user_id=user_id, auth_strength=AuthStrength.AAL1)

    response = await client.get("/v1/me/workspaces", headers=_auth_headers(session_record.id))
    assert response.status_code == 200
    assert response.json() == []


async def test_plain_member_sees_workspaces_they_are_explicitly_added_to(
    client: AsyncClient, db_available: bool
) -> None:
    customer_id = uuid.uuid4()
    user_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as db:
        db.add(User(id=user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Member"))
        await db.flush()

        _customer, owner_membership = await create_customer_with_owner(
            db, customer_id=customer_id, name="Acme", owner_user_id=uuid.uuid4(), actor_id="user:setup"
        )
        member_membership = await invite_customer_member(
            db, customer_id=customer_id, user_id=user_id, role=CustomerRole.MEMBER, actor_id="user:setup"
        )
        workspace_a = await create_workspace(db, customer_id=customer_id, name="A")
        await create_workspace(db, customer_id=customer_id, name="B")  # not added to this one
        await add_workspace_member(
            db,
            workspace=workspace_a,
            customer_membership=member_membership,
            role="member",
            actor_id="user:setup",
        )
        session_record = await create_session(db, user_id=user_id, auth_strength=AuthStrength.AAL1)

    response = await client.get("/v1/me/workspaces", headers=_auth_headers(session_record.id))
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["workspace_id"] == str(workspace_a.id)
    assert body[0]["workspace_name"] == "A"
    assert body[0]["customer_id"] == str(customer_id)
    assert body[0]["role"] == "member"


async def test_customer_owner_sees_every_workspace_with_no_explicit_membership_rows(
    client: AsyncClient, db_available: bool
) -> None:
    """The CustomerOwner authority fix (get_workspace_context) means an
    owner has full access to every workspace under their customer even
    with zero WorkspaceMembership rows — this listing must reflect that,
    not just the explicit-membership case."""
    customer_id = uuid.uuid4()
    owner_user_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as db:
        db.add(User(id=owner_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Owner"))
        await db.flush()

        await create_customer_with_owner(
            db, customer_id=customer_id, name="Acme", owner_user_id=owner_user_id, actor_id="user:setup"
        )
        await create_workspace(db, customer_id=customer_id, name="A")
        await create_workspace(db, customer_id=customer_id, name="B")
        session_record = await create_session(db, user_id=owner_user_id, auth_strength=AuthStrength.AAL1)

    response = await client.get("/v1/me/workspaces", headers=_auth_headers(session_record.id))
    assert response.status_code == 200
    body = response.json()
    assert {entry["workspace_name"] for entry in body} == {"A", "B"}
    assert all(entry["role"] == "workspace_admin" for entry in body)


async def test_workspaces_from_two_different_customers_both_appear(
    client: AsyncClient, db_available: bool
) -> None:
    user_id = uuid.uuid4()
    customer_1_id = uuid.uuid4()
    customer_2_id = uuid.uuid4()

    async with tenant_scoped_session(customer_1_id) as db:
        db.add(User(id=user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Multi-org"))
        await db.flush()
        await create_customer_with_owner(
            db, customer_id=customer_1_id, name="Customer One", owner_user_id=user_id, actor_id="user:setup"
        )
        await create_workspace(db, customer_id=customer_1_id, name="One's workspace")
        session_record = await create_session(db, user_id=user_id, auth_strength=AuthStrength.AAL1)

    async with tenant_scoped_session(customer_2_id) as db:
        await create_customer_with_owner(
            db, customer_id=customer_2_id, name="Customer Two", owner_user_id=user_id, actor_id="user:setup"
        )
        await create_workspace(db, customer_id=customer_2_id, name="Two's workspace")

    response = await client.get("/v1/me/workspaces", headers=_auth_headers(session_record.id))
    assert response.status_code == 200
    body = response.json()
    seen_customer_names = {entry["customer_name"] for entry in body}
    seen_workspace_names = {entry["workspace_name"] for entry in body}
    assert seen_customer_names == {"Customer One", "Customer Two"}
    assert seen_workspace_names == {"One's workspace", "Two's workspace"}


async def test_removed_member_no_longer_sees_the_workspace(client: AsyncClient, db_available: bool) -> None:
    """Proves UserCustomerIndex is actually cleaned up on removal, not just
    written on invite — a stale index row would still 200 with an empty
    list here (list_my_workspaces would find zero WorkspaceMembership rows
    once the CustomerMembership is gone), so this mainly guards against
    remove_customer_member forgetting the index cleanup and leaving a
    row that would resurface if the user were re-invited without a fresh
    invite ever re-adding it — see the (user_id, customer_id) uniqueness
    reasoning in UserCustomerIndex's docstring."""
    customer_id = uuid.uuid4()
    user_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as db:
        db.add(User(id=user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Temp"))
        await db.flush()
        await create_customer_with_owner(
            db, customer_id=customer_id, name="Acme", owner_user_id=uuid.uuid4(), actor_id="user:setup"
        )
        membership = await invite_customer_member(
            db, customer_id=customer_id, user_id=user_id, role=CustomerRole.MEMBER, actor_id="user:setup"
        )
        workspace = await create_workspace(db, customer_id=customer_id, name="A")
        await add_workspace_member(
            db, workspace=workspace, customer_membership=membership, role="member", actor_id="user:setup"
        )
        session_record = await create_session(db, user_id=user_id, auth_strength=AuthStrength.AAL1)

    response_before = await client.get("/v1/me/workspaces", headers=_auth_headers(session_record.id))
    assert len(response_before.json()) == 1

    async with tenant_scoped_session(customer_id) as db:
        fresh_membership = await db.get(CustomerMembership, membership.id)
        await remove_customer_member(db, fresh_membership, actor_id="user:setup")

    async with async_session_factory() as db:
        index_row = await db.get(UserCustomerIndex, {"user_id": user_id, "customer_id": customer_id})
        assert index_row is None

    response_after = await client.get("/v1/me/workspaces", headers=_auth_headers(session_record.id))
    assert response_after.status_code == 200
    assert response_after.json() == []
