"""FR-WKS-001/005 — Customer creation and membership invariants, against a
live Postgres. The "last owner" protection is the negative test the TRD
explicitly calls for (FR-WKS-005: "oxirgi Owner chiqarib bo'lmaydi")."""

import uuid

import pytest

from doda.application.customer_service import (
    CustomerMembershipError,
    change_customer_member_role,
    create_customer_with_owner,
    invite_customer_member,
    remove_customer_member,
)
from doda.application.workspace_service import add_workspace_member, create_workspace
from doda.db import tenant_scoped_session
from doda.domain.security.roles import CustomerRole
from doda.domain.workspace.models import WorkspaceMembership


async def test_create_customer_with_owner(db_available: bool) -> None:
    owner_user_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        customer, membership = await create_customer_with_owner(
            session,
            customer_id=customer_id,
            name="Acme",
            owner_user_id=owner_user_id,
            actor_id="user:bootstrap",
        )
        assert membership.role == CustomerRole.CUSTOMER_OWNER.value
        assert membership.user_id == owner_user_id
        assert membership.customer_id == customer.id


async def test_cannot_demote_the_last_owner(db_available: bool) -> None:
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        customer, owner_membership = await create_customer_with_owner(
            session,
            customer_id=customer_id,
            name="Acme",
            owner_user_id=uuid.uuid4(),
            actor_id="user:bootstrap",
        )
        with pytest.raises(CustomerMembershipError, match="last customer_owner"):
            await change_customer_member_role(
                session, owner_membership, new_role=CustomerRole.MEMBER, actor_id="user:bootstrap"
            )


async def test_can_demote_an_owner_when_another_owner_exists(db_available: bool) -> None:
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        customer, first_owner = await create_customer_with_owner(
            session,
            customer_id=customer_id,
            name="Acme",
            owner_user_id=uuid.uuid4(),
            actor_id="user:bootstrap",
        )
        second_owner = await invite_customer_member(
            session,
            customer_id=customer.id,
            user_id=uuid.uuid4(),
            role=CustomerRole.CUSTOMER_OWNER,
            actor_id="user:bootstrap",
        )
        # Two owners now — demoting the first one is fine.
        await change_customer_member_role(
            session, first_owner, new_role=CustomerRole.MEMBER, actor_id="user:bootstrap"
        )
        assert first_owner.role == CustomerRole.MEMBER.value
        assert second_owner.role == CustomerRole.CUSTOMER_OWNER.value


async def test_cannot_remove_the_last_owner(db_available: bool) -> None:
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        customer, owner_membership = await create_customer_with_owner(
            session,
            customer_id=customer_id,
            name="Acme",
            owner_user_id=uuid.uuid4(),
            actor_id="user:bootstrap",
        )
        with pytest.raises(CustomerMembershipError, match="last customer_owner"):
            await remove_customer_member(session, owner_membership, actor_id="user:bootstrap")


async def test_removing_customer_member_cascades_workspace_memberships(db_available: bool) -> None:
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        customer, owner_membership = await create_customer_with_owner(
            session,
            customer_id=customer_id,
            name="Acme",
            owner_user_id=uuid.uuid4(),
            actor_id="user:bootstrap",
        )
        member = await invite_customer_member(
            session,
            customer_id=customer.id,
            user_id=uuid.uuid4(),
            role=CustomerRole.MEMBER,
            actor_id="user:bootstrap",
        )
        workspace = await create_workspace(session, customer_id=customer.id, name="Main")
        workspace_membership = await add_workspace_member(
            session,
            workspace=workspace,
            customer_membership=member,
            role="member",
            actor_id="user:bootstrap",
        )

        await remove_customer_member(session, member, actor_id="user:bootstrap")

        remaining = await session.get(WorkspaceMembership, workspace_membership.id)
        assert remaining is None
