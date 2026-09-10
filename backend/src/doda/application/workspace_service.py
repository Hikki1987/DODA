"""Workspace lifecycle — FR-WKS-002/005/006. Membership management here
operates on an existing CustomerMembership, never a bare user_id (FR-WKS-003:
"UserId'ga bevosita workspace biriktirish urinishi rad etiladi") — see
add_workspace_member's signature and negative test in
tests/integration/test_workspace_admin_api.py.
"""

import dataclasses
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from doda.application.audit_service import record_audit_event
from doda.db import async_session_factory, tenant_scoped_session
from doda.domain.base import utcnow
from doda.domain.customer.models import Customer, CustomerMembership, UserCustomerIndex
from doda.domain.identity.models import User
from doda.domain.security.roles import CustomerRole
from doda.domain.workspace.models import Workspace, WorkspaceMembership, WorkspaceTenantIndex


class WorkspaceMembershipError(Exception):
    """A well-formed request that violates a business rule (e.g. the target
    CustomerMembership belongs to a different customer). Distinct from
    AuthorizationError: this is not about the caller's permissions."""


class DuplicateWorkspaceMembershipError(Exception):
    """Raised by add_workspace_member when this CustomerMembership already
    has a WorkspaceMembership row for this workspace — see
    customer_service.DuplicateMembershipError's docstring for why this
    needs its own race-safe check (no unique constraint otherwise stops a
    double-clicked "Qo'shish" or two concurrent adds from creating two
    independent membership rows for the same person)."""


async def create_workspace(
    session: AsyncSession, *, customer_id: uuid.UUID, name: str, actor_id: str = "system:provisioning"
) -> Workspace:
    workspace = Workspace(customer_id=customer_id, name=name)
    session.add(workspace)
    await session.flush()
    session.add(WorkspaceTenantIndex(workspace_id=workspace.id, customer_id=customer_id))
    await record_audit_event(
        session,
        customer_id=customer_id,
        workspace_id=workspace.id,
        trace_id=uuid.uuid4(),
        actor_id=actor_id,
        event_type="workspace.created.v1",
        safe_metadata={"workspace_id": str(workspace.id), "name": name},
    )
    await session.flush()
    return workspace


async def add_workspace_member(
    session: AsyncSession,
    *,
    workspace: Workspace,
    customer_membership: CustomerMembership,
    role: str,
    actor_id: str,
) -> WorkspaceMembership:
    if customer_membership.customer_id != workspace.customer_id:
        raise WorkspaceMembershipError(
            "customer_membership belongs to a different customer than this workspace"
        )

    if customer_membership.role == CustomerRole.AUDITOR.value:
        # An auditor is read-only (10.2), and get_workspace_context refuses to
        # resolve one into a WorkspaceRole at all — so such a row could only
        # ever be a powerless membership that looks like a granted role in the
        # members list. Refuse it at the source with a clear 409 instead.
        raise WorkspaceMembershipError("an auditor cannot hold a workspace role")

    membership = WorkspaceMembership(
        customer_id=workspace.customer_id,
        customer_membership_id=customer_membership.id,
        workspace_id=workspace.id,
        role=role,
    )
    try:
        async with session.begin_nested():
            session.add(membership)
            await session.flush()
    except IntegrityError as exc:
        raise DuplicateWorkspaceMembershipError(
            "this customer membership already has a role in this workspace"
        ) from exc

    await record_audit_event(
        session,
        customer_id=workspace.customer_id,
        workspace_id=workspace.id,
        trace_id=uuid.uuid4(),
        actor_id=actor_id,
        event_type="workspace.member_added.v1",
        safe_metadata={
            "workspace_id": str(workspace.id),
            "workspace_membership_id": str(membership.id),
            "role": role,
        },
    )
    return membership


async def change_workspace_member_role(
    session: AsyncSession, membership: WorkspaceMembership, *, new_role: str, actor_id: str
) -> WorkspaceMembership:
    previous_role = membership.role
    membership.role = new_role
    await session.flush()
    await record_audit_event(
        session,
        customer_id=membership.customer_id,
        workspace_id=membership.workspace_id,
        trace_id=uuid.uuid4(),
        actor_id=actor_id,
        event_type="workspace.member_role_changed.v1",
        safe_metadata={
            "workspace_membership_id": str(membership.id),
            "from_role": previous_role,
            "to_role": new_role,
        },
    )
    return membership


async def remove_workspace_member(
    session: AsyncSession, membership: WorkspaceMembership, *, actor_id: str
) -> None:
    await record_audit_event(
        session,
        customer_id=membership.customer_id,
        workspace_id=membership.workspace_id,
        trace_id=uuid.uuid4(),
        actor_id=actor_id,
        event_type="workspace.member_removed.v1",
        safe_metadata={"workspace_membership_id": str(membership.id), "role": membership.role},
    )
    await session.delete(membership)
    await session.flush()


async def archive_workspace(session: AsyncSession, workspace: Workspace, *, actor_id: str) -> Workspace:
    """FR-WKS-006. get_workspace_context already treats archived_at IS NOT
    NULL as DENY (see authz_service), so archiving takes effect for every
    endpoint immediately — no separate enforcement needed here."""
    workspace.archived_at = utcnow()
    await session.flush()
    await record_audit_event(
        session,
        customer_id=workspace.customer_id,
        workspace_id=workspace.id,
        trace_id=uuid.uuid4(),
        actor_id=actor_id,
        event_type="workspace.archived.v1",
        safe_metadata={"workspace_id": str(workspace.id)},
    )
    return workspace


async def restore_workspace(session: AsyncSession, workspace: Workspace, *, actor_id: str) -> Workspace:
    workspace.archived_at = None
    await session.flush()
    await record_audit_event(
        session,
        customer_id=workspace.customer_id,
        workspace_id=workspace.id,
        trace_id=uuid.uuid4(),
        actor_id=actor_id,
        event_type="workspace.restored.v1",
        safe_metadata={"workspace_id": str(workspace.id)},
    )
    return workspace


@dataclasses.dataclass(frozen=True)
class MyWorkspaceEntry:
    customer_id: uuid.UUID
    customer_name: str
    workspace_id: uuid.UUID
    workspace_name: str
    role: str


async def list_my_workspaces(user_id: uuid.UUID) -> list[MyWorkspaceEntry]:
    """The one query every client needs before it can call anything else in
    this API: "which workspaces am I in." There was no way to answer this
    before UserCustomerIndex existed — every other endpoint requires the
    caller to already know a workspace_id or customer_id up front.

    Manages its own sessions rather than taking one as a parameter: this
    inherently spans multiple tenant contexts (the bootstrap index lookup,
    then one tenant_scoped_session per customer the user belongs to), the
    same shape api.dependencies._resolve_request_context already uses.

    Both branches below carry an explicit customer_id predicate even
    though tenant_scoped_session's RLS GUC already scopes them (6.2:
    repository-layer customer_id filtering is the FIRST, independent
    isolation layer, RLS the second — neither substitutes for the other,
    and this codebase has already had RLS silently no-op in a fresh/
    production environment once, see ADR-005). This is the first query
    any client makes after login, with no prior authorized workspace_id
    to have already narrowed the search — a security review flagged its
    missing first-layer filter as the one query in this function without
    one.
    """
    async with async_session_factory() as db:
        customer_ids = (
            await db.scalars(
                select(UserCustomerIndex.customer_id).where(UserCustomerIndex.user_id == user_id)
            )
        ).all()

    entries: list[MyWorkspaceEntry] = []
    for customer_id in customer_ids:
        async with tenant_scoped_session(customer_id) as db:
            customer = await db.get(Customer, customer_id)
            assert customer is not None  # UserCustomerIndex only ever mirrors a real Customer

            role = await db.scalar(
                select(CustomerMembership.role).where(
                    CustomerMembership.customer_id == customer_id, CustomerMembership.user_id == user_id
                )
            )
            if role == CustomerRole.CUSTOMER_OWNER.value:
                # See authz_service.get_workspace_context: a CustomerOwner
                # has WORKSPACE_ADMIN authority over every workspace under
                # their customer, even with no WorkspaceMembership row at
                # all — this listing must not silently omit those.
                workspaces = await db.scalars(
                    select(Workspace).where(
                        Workspace.customer_id == customer_id, Workspace.archived_at.is_(None)
                    )
                )
                entries.extend(
                    MyWorkspaceEntry(
                        customer_id=customer_id,
                        customer_name=customer.name,
                        workspace_id=workspace.id,
                        workspace_name=workspace.name,
                        role="workspace_admin",
                    )
                    for workspace in workspaces
                )
            elif role == CustomerRole.AUDITOR.value:
                # An auditor holds no workspace role at all (10.2; enforced in
                # authz_service.get_workspace_context), so listing a workspace
                # for them here would advertise a page every request to which
                # then 403s. A stale WorkspaceMembership row can still exist —
                # add_workspace_member refuses to create one, but a plain
                # member with a workspace role who is later demoted to auditor
                # keeps theirs — so this has to be skipped explicitly, not
                # assumed absent.
                continue
            else:
                rows = await db.execute(
                    select(Workspace, WorkspaceMembership.role)
                    .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
                    .join(
                        CustomerMembership,
                        CustomerMembership.id == WorkspaceMembership.customer_membership_id,
                    )
                    .where(
                        CustomerMembership.customer_id == customer_id,
                        CustomerMembership.user_id == user_id,
                        Workspace.archived_at.is_(None),
                    )
                )
                entries.extend(
                    MyWorkspaceEntry(
                        customer_id=customer_id,
                        customer_name=customer.name,
                        workspace_id=workspace.id,
                        workspace_name=workspace.name,
                        role=workspace_role,
                    )
                    for workspace, workspace_role in rows
                )
    return entries


async def list_archived_workspaces(session: AsyncSession, *, customer_id: uuid.UUID) -> list[Workspace]:
    """The gap CLAUDE.md's "Bilingan cheklovlar" flagged: archive/restore
    (FR-WKS-006) already existed, but nothing let a client discover a
    workspace's id once GET /v1/me/workspaces stopped surfacing it
    (list_my_workspaces filters archived_at IS NULL unconditionally) — a
    workspace archived through the UI had no UI path back. This is the
    missing "which workspace ids are archived" lookup; restore_workspace
    itself is unchanged."""
    rows = await session.scalars(
        select(Workspace)
        .where(Workspace.customer_id == customer_id, Workspace.archived_at.is_not(None))
        .order_by(Workspace.archived_at.desc())
    )
    return list(rows)


@dataclasses.dataclass(frozen=True)
class WorkspaceMemberEntry:
    membership_id: uuid.UUID | None
    """None for a CustomerOwner shown here on implicit authority alone —
    see the docstring below. There is no WorkspaceMembership row to
    PATCH/DELETE in that case; the roster still must show them, or a
    workspace_admin managing "who's on my team" would get a materially
    wrong answer, the same reasoning as list_my_workspaces's CustomerOwner
    special case."""
    user_id: uuid.UUID
    display_name: str
    role: str


async def list_workspace_members(
    session: AsyncSession, *, workspace_id: uuid.UUID
) -> list[WorkspaceMemberEntry]:
    """There was no way to see who is actually in a workspace at all before
    this — add/change-role/remove all existed, but nothing to list the
    current roster, the same class of gap GET /v1/me/workspaces and the
    task/action list endpoints already closed elsewhere."""
    rows = await session.execute(
        select(WorkspaceMembership, CustomerMembership.user_id, User.display_name)
        .join(CustomerMembership, CustomerMembership.id == WorkspaceMembership.customer_membership_id)
        .join(User, User.id == CustomerMembership.user_id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
    )
    entries = [
        WorkspaceMemberEntry(
            membership_id=membership.id, user_id=user_id, display_name=display_name, role=membership.role
        )
        for membership, user_id, display_name in rows
    ]
    explicit_user_ids = {entry.user_id for entry in entries}

    workspace = await session.get(Workspace, workspace_id)
    assert workspace is not None
    owners = await session.execute(
        select(CustomerMembership.user_id, User.display_name)
        .join(User, User.id == CustomerMembership.user_id)
        .where(
            CustomerMembership.customer_id == workspace.customer_id,
            CustomerMembership.role == CustomerRole.CUSTOMER_OWNER.value,
        )
    )
    for owner_user_id, owner_display_name in owners:
        if owner_user_id not in explicit_user_ids:
            entries.append(
                WorkspaceMemberEntry(
                    membership_id=None,
                    user_id=owner_user_id,
                    display_name=owner_display_name,
                    role="workspace_admin",
                )
            )
    return entries
