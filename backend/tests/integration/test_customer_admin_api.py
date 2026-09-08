"""HTTP tests for customer membership management (FR-WKS-005) —
customer_service.invite_customer_member/change_customer_member_role/
remove_customer_member had no HTTP surface at all until api/customer_admin.py
(previously flagged in CLAUDE.md as a known gap: workspace-level membership
had an API, customer-level never did). Application-layer invariants
(last-owner protection) are already covered in test_customer_service.py;
this file proves the authz gate and wiring over real HTTP instead.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from doda.application.customer_service import create_customer_with_owner, invite_customer_member
from doda.application.session_service import create_session
from doda.db import tenant_scoped_session
from doda.domain.customer.models import CustomerMembership
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


async def _seed_customer_with_owner(*, owner_auth_strength: AuthStrength = AuthStrength.AAL1):
    """A fresh Customer with a real Identity User as its sole customer_owner
    and a live Session — the minimal setup every test here starts from."""
    owner_user_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        session.add(User(id=owner_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Owner"))
        await session.flush()
        await create_customer_with_owner(
            session, customer_id=customer_id, name="Acme", owner_user_id=owner_user_id, actor_id="user:setup"
        )
        owner_session = await create_session(
            session, user_id=owner_user_id, auth_strength=owner_auth_strength
        )
    return customer_id, owner_user_id, owner_session.id


async def _add_plain_member(customer_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """A second real Identity User invited as a plain 'member' of the same
    customer, with their own live session. Returns (user_id, session_id)."""
    member_user_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        session.add(User(id=member_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Member"))
        await session.flush()
        await invite_customer_member(
            session,
            customer_id=customer_id,
            user_id=member_user_id,
            role=CustomerRole.MEMBER,
            actor_id="user:setup",
        )
        member_session = await create_session(
            session, user_id=member_user_id, auth_strength=AuthStrength.AAL1
        )
    return member_user_id, member_session.id


async def test_plain_member_cannot_invite_customer_members(client: AsyncClient, db_available: bool) -> None:
    customer_id, _owner_id, owner_session_id = await _seed_customer_with_owner()
    _member_user_id, member_session_id = await _add_plain_member(customer_id)

    response = await client.post(
        f"/v1/customers/{customer_id}/members",
        json={"user_id": str(uuid.uuid4()), "role": "member"},
        headers=_auth_headers(member_session_id),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"


async def test_customer_owner_can_invite_change_role_and_remove_a_member(
    client: AsyncClient, db_available: bool
) -> None:
    customer_id, _owner_id, owner_session_id = await _seed_customer_with_owner()

    candidate_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        session.add(User(id=candidate_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Candidate"))
        await session.commit()

    invite_response = await client.post(
        f"/v1/customers/{customer_id}/members",
        json={"user_id": str(candidate_id), "role": "member"},
        headers=_auth_headers(owner_session_id),
    )
    assert invite_response.status_code == 200
    body = invite_response.json()
    assert body["user_id"] == str(candidate_id)
    assert body["role"] == "member"
    membership_id = body["id"]

    change_response = await client.patch(
        f"/v1/customers/{customer_id}/members/{membership_id}",
        json={"role": "auditor"},
        headers=_auth_headers(owner_session_id),
    )
    assert change_response.status_code == 200
    assert change_response.json()["role"] == "auditor"

    remove_response = await client.delete(
        f"/v1/customers/{customer_id}/members/{membership_id}",
        headers=_auth_headers(owner_session_id),
    )
    assert remove_response.status_code == 204


async def test_inviting_a_nonexistent_user_is_not_found(client: AsyncClient, db_available: bool) -> None:
    customer_id, _owner_id, owner_session_id = await _seed_customer_with_owner()

    response = await client.post(
        f"/v1/customers/{customer_id}/members",
        json={"user_id": str(uuid.uuid4()), "role": "member"},
        headers=_auth_headers(owner_session_id),
    )
    assert response.status_code == 404


async def test_customer_owner_cannot_manage_members_of_a_different_customer(
    client: AsyncClient, db_available: bool
) -> None:
    _customer_a_id, _owner_a_id, owner_a_session_id = await _seed_customer_with_owner()
    customer_b_id, _owner_b_id, _owner_b_session_id = await _seed_customer_with_owner()
    _member_b_user_id, _member_b_session_id = await _add_plain_member(customer_b_id)

    # Owner A authenticates fine (their own session is real) but has no
    # CustomerMembership under customer B at all.
    response = await client.post(
        f"/v1/customers/{customer_b_id}/members",
        json={"user_id": str(uuid.uuid4()), "role": "member"},
        headers=_auth_headers(owner_a_session_id),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"


async def test_cannot_demote_the_last_owner_over_http(client: AsyncClient, db_available: bool) -> None:
    customer_id, owner_id, owner_session_id = await _seed_customer_with_owner()

    async with tenant_scoped_session(customer_id) as session:
        membership_id = await session.scalar(
            select(CustomerMembership.id).where(
                CustomerMembership.customer_id == customer_id, CustomerMembership.user_id == owner_id
            )
        )

    response = await client.patch(
        f"/v1/customers/{customer_id}/members/{membership_id}",
        json={"role": "member"},
        headers=_auth_headers(owner_session_id),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "LAST_OWNER_PROTECTED"


async def test_list_customer_members_shows_owner_and_invited_member(
    client: AsyncClient, db_available: bool
) -> None:
    """There was no way to see the current roster at all before this —
    invite/change-role/remove all existed, but nothing to list who's
    actually in the customer."""
    customer_id, _owner_id, owner_session_id = await _seed_customer_with_owner()
    member_user_id, _member_session_id = await _add_plain_member(customer_id)

    response = await client.get(
        f"/v1/customers/{customer_id}/members", headers=_auth_headers(owner_session_id)
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2

    by_user_id = {entry["user_id"]: entry for entry in body}
    assert by_user_id[str(member_user_id)]["role"] == "member"
    assert all(entry["display_name"] for entry in body)
