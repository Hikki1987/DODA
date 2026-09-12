"""get_workspace_context's CustomerRole.CUSTOMER_OWNER resolution, against
a live Postgres — the real fix for a gap flagged since S2: previously
only WorkspaceRole was checked anywhere, so a CustomerOwner with no
WorkspaceMembership row at all was wrongly denied at the very first step
(get_request_context), before any authorize_* function ever ran.
"""

import uuid

from doda.application.authz_service import get_workspace_context
from doda.application.workspace_service import create_workspace
from doda.domain.customer.models import Customer, CustomerMembership
from doda.domain.security.roles import WorkspaceRole


async def test_customer_owner_resolves_as_workspace_admin_with_no_membership_row(
    tenant_session,
) -> None:
    customer_id, session = tenant_session
    owner_user_id = uuid.uuid4()
    session.add(Customer(id=customer_id, name="Acme"))
    session.add(CustomerMembership(customer_id=customer_id, user_id=owner_user_id, role="customer_owner"))
    workspace = await create_workspace(session, customer_id=customer_id, name="Main")

    context = await get_workspace_context(session, user_id=owner_user_id, workspace_id=workspace.id)

    assert context.role is WorkspaceRole.WORKSPACE_ADMIN
    assert context.customer_id == customer_id


async def test_customer_owner_authority_overrides_a_lower_explicit_workspace_role(
    tenant_session,
) -> None:
    """A CustomerOwner who was ALSO explicitly added as a plain "member" of
    a workspace must still get their full CustomerOwner authority, not the
    lower explicit role — being added to one workspace should never reduce
    what you can already do everywhere in your own customer."""
    from doda.application.workspace_service import add_workspace_member

    customer_id, session = tenant_session
    owner_user_id = uuid.uuid4()
    session.add(Customer(id=customer_id, name="Acme"))
    owner_membership = CustomerMembership(
        customer_id=customer_id, user_id=owner_user_id, role="customer_owner"
    )
    session.add(owner_membership)
    await session.flush()

    workspace = await create_workspace(session, customer_id=customer_id, name="Main")
    await add_workspace_member(
        session,
        workspace=workspace,
        customer_membership=owner_membership,
        role="member",
        actor_id="user:setup",
    )

    context = await get_workspace_context(session, user_id=owner_user_id, workspace_id=workspace.id)

    assert context.role is WorkspaceRole.WORKSPACE_ADMIN


async def test_plain_member_without_customer_owner_role_keeps_their_real_role(
    tenant_session,
) -> None:
    """Sanity check that the fix didn't accidentally elevate everyone: a
    non-owner member must still resolve to their real, lower role."""
    from doda.application.workspace_service import add_workspace_member

    customer_id, session = tenant_session
    member_user_id = uuid.uuid4()
    session.add(Customer(id=customer_id, name="Acme"))
    member_membership = CustomerMembership(customer_id=customer_id, user_id=member_user_id, role="member")
    session.add(member_membership)
    await session.flush()

    workspace = await create_workspace(session, customer_id=customer_id, name="Main")
    await add_workspace_member(
        session,
        workspace=workspace,
        customer_membership=member_membership,
        role="member",
        actor_id="user:setup",
    )

    context = await get_workspace_context(session, user_id=member_user_id, workspace_id=workspace.id)

    assert context.role is WorkspaceRole.MEMBER
