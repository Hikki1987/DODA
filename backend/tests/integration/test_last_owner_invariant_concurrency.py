"""Proves FR-WKS-005's "cannot remove the last customer_owner" invariant
survives concurrency, not just sequential calls (the existing sequential
tests in test_customer_service.py never race two requests against each
other). A customer with exactly two owners, A and B, where A removes B and
B removes A at the same moment — each believing "the other owner is still
there" — must not both succeed: that would leave the customer with zero
owners and no customer_owner left to ever invite a new one, through the
API or otherwise.

Found via the same forced-interleaving technique as the Task/Action/
kill-switch concurrency fixes: both calls load their target membership
and count the other as still present before either commits.
"""

import asyncio
import uuid

from sqlalchemy import select

from doda.application.customer_service import (
    CustomerMembershipError,
    create_customer_with_owner,
    invite_customer_member,
    remove_customer_member,
)
from doda.db import tenant_scoped_session
from doda.domain.customer.models import CustomerMembership
from doda.domain.identity.models import User
from doda.domain.security.roles import CustomerRole


async def test_two_owners_cannot_both_remove_each_other_down_to_zero(db_available: bool) -> None:
    customer_id = uuid.uuid4()

    async with tenant_scoped_session(customer_id) as session:
        user_a = User(oidc_subject_hash=str(uuid.uuid4()), display_name="Owner A")
        user_b = User(oidc_subject_hash=str(uuid.uuid4()), display_name="Owner B")
        session.add(user_a)
        session.add(user_b)
        await session.flush()

        _, membership_a = await create_customer_with_owner(
            session, customer_id=customer_id, name="Race Co", owner_user_id=user_a.id, actor_id="user:seed"
        )
        membership_b = await invite_customer_member(
            session,
            customer_id=customer_id,
            user_id=user_b.id,
            role=CustomerRole.CUSTOMER_OWNER,
            actor_id="user:seed",
        )
        membership_a_id, membership_b_id = membership_a.id, membership_b.id

    cm1 = tenant_scoped_session(customer_id)
    cm2 = tenant_scoped_session(customer_id)
    session1 = await cm1.__aenter__()
    session2 = await cm2.__aenter__()

    # Both "requests" load their target membership while both owners are
    # still present — the actual race window.
    b_as_seen_by_1 = await session1.get(CustomerMembership, membership_b_id)
    a_as_seen_by_2 = await session2.get(CustomerMembership, membership_a_id)

    async def remove(cm, session, membership, actor):
        try:
            await remove_customer_member(session, membership, actor_id=actor)
        except CustomerMembershipError as exc:
            await cm.__aexit__(type(exc), exc, exc.__traceback__)
            return "rejected"
        else:
            await cm.__aexit__(None, None, None)
            return "ok"

    results = await asyncio.gather(
        remove(cm1, session1, b_as_seen_by_1, "user:a"),  # A removes B
        remove(cm2, session2, a_as_seen_by_2, "user:b"),  # B removes A
    )

    # Exactly one removal wins; the other is correctly rejected once it
    # re-counts owners under the winner's already-committed change.
    assert sorted(results) == ["ok", "rejected"]

    async with tenant_scoped_session(customer_id) as session:
        remaining_owners = (
            (
                await session.execute(
                    select(CustomerMembership).where(
                        CustomerMembership.customer_id == customer_id,
                        CustomerMembership.role == CustomerRole.CUSTOMER_OWNER.value,
                    )
                )
            )
            .scalars()
            .all()
        )

    # Never zero — that would permanently strand the customer with no
    # owner able to manage it through the API.
    assert len(remaining_owners) == 1
