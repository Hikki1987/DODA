"""Authorization — section 10's chain, the part after session resolution:
Customer Membership -> Workspace Membership -> RBAC -> (Step-Up). Every
function here raises on anything short of an explicit ALLOW (10.1:
fail-closed) rather than defaulting to permit.
"""

import dataclasses
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doda.domain.action.models import Action
from doda.domain.customer.models import Customer, CustomerMembership
from doda.domain.identity.models import AuthStrength
from doda.domain.security.decisions import Decision
from doda.domain.security.roles import (
    ROLES_THAT_MAY_APPROVE_ANOTHER_ACTORS_ACTION,
    ROLES_THAT_MAY_PROPOSE_ACTIONS,
    CustomerRole,
    WorkspaceRole,
)
from doda.domain.task.models import Task
from doda.domain.workspace.models import Workspace, WorkspaceMembership


class AuthorizationError(Exception):
    def __init__(self, decision: Decision, reason: str) -> None:
        self.decision = decision
        # `reason` is for server-side logs/audit only — never put it verbatim
        # in an API response body (10.1: "sezgir tafsilot ko'rsatilmaydi").
        super().__init__(reason)


@dataclasses.dataclass(frozen=True)
class WorkspaceContext:
    customer_id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    role: WorkspaceRole


async def _is_customer_owner(session: AsyncSession, *, user_id: uuid.UUID, customer_id: uuid.UUID) -> bool:
    role = await session.scalar(
        select(CustomerMembership.role).where(
            CustomerMembership.customer_id == customer_id, CustomerMembership.user_id == user_id
        )
    )
    return role == CustomerRole.CUSTOMER_OWNER.value


async def get_workspace_context(
    session: AsyncSession, *, user_id: uuid.UUID, workspace_id: uuid.UUID, allow_archived: bool = False
) -> WorkspaceContext:
    """NFR-ISO-002: never look up a workspace by id alone — always through
    the membership chain, so a user with no membership gets DENY, not a
    lookup of a workspace that happens to belong to someone else's customer.

    `allow_archived` exists only for the restore flow (FR-WKS-006): a
    workspace that's archived must otherwise be closed to retrieval and
    action (fail-closed default), but *restoring* it necessarily requires
    resolving context for that same archived workspace — see
    api.dependencies.get_request_context_allow_archived, used nowhere else.

    A CustomerRole.CUSTOMER_OWNER resolves here as WorkspaceRole.WORKSPACE_ADMIN
    for ANY workspace under their customer, even with no WorkspaceMembership
    row at all — 10.2 grants CustomerOwner the same or greater authority
    than WorkspaceAdmin on every row that has a WorkspaceAdmin column
    (role assignment, R3 approval, etc). Checked first and unconditionally
    (not merely as a fallback after membership lookup fails): a customer
    owner's authority does not depend on whether someone also happened to
    add them as a plain "member" of this particular workspace.
    """
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or (workspace.archived_at is not None and not allow_archived):
        raise AuthorizationError(Decision.DENY, "workspace not found or archived")

    if await _is_customer_owner(session, user_id=user_id, customer_id=workspace.customer_id):
        return WorkspaceContext(
            customer_id=workspace.customer_id,
            workspace_id=workspace_id,
            user_id=user_id,
            role=WorkspaceRole.WORKSPACE_ADMIN,
        )

    row = (
        await session.execute(
            select(WorkspaceMembership, CustomerMembership.role)
            .join(
                CustomerMembership,
                CustomerMembership.id == WorkspaceMembership.customer_membership_id,
            )
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                CustomerMembership.user_id == user_id,
            )
        )
    ).first()
    if row is None:
        raise AuthorizationError(Decision.DENY, "no workspace membership")

    membership, _customer_role = row
    return WorkspaceContext(
        customer_id=workspace.customer_id,
        workspace_id=workspace_id,
        user_id=user_id,
        role=WorkspaceRole(membership.role),
    )


def authorize_propose_action(context: WorkspaceContext) -> None:
    if context.role not in ROLES_THAT_MAY_PROPOSE_ACTIONS:
        raise AuthorizationError(Decision.DENY, f"role {context.role.value} may not propose actions")


def authorize_consume_approval(
    context: WorkspaceContext, action: Action, *, auth_strength: AuthStrength
) -> None:
    """9.1: R3's approver is 'the user themself' under fresh MFA; a
    WorkspaceRole.WORKSPACE_ADMIN may additionally approve someone else's
    action (10.2: 'R3 action bajarish' is 'Approval bilan' for
    Member/WorkspaceAdmin/CustomerOwner alike — a CustomerOwner already
    resolves as WORKSPACE_ADMIN here, see get_workspace_context). Auditor
    can never approve, full stop.
    """
    is_self_approval = action.actor_id == f"user:{context.user_id}"
    if not is_self_approval and context.role not in ROLES_THAT_MAY_APPROVE_ANOTHER_ACTORS_ACTION:
        raise AuthorizationError(Decision.DENY, f"role {context.role.value} may not approve this action")

    if auth_strength is not AuthStrength.AAL2:
        raise AuthorizationError(
            Decision.STEP_UP_REQUIRED, "R3+ approval requires fresh MFA (FR-AUTH-004)"
        )


def authorize_create_task(context: WorkspaceContext) -> None:
    """10.2 'Chat va task' row: Member/WorkspaceAdmin/CustomerOwner = Ha.
    Written as an explicit check (not a no-op) so a future third
    WorkspaceRole with no task rights fails closed instead of slipping
    through by omission."""
    if context.role not in (WorkspaceRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN):
        raise AuthorizationError(Decision.DENY, f"role {context.role.value} may not create tasks")


def authorize_manage_workspace_members(context: WorkspaceContext) -> None:
    """10.2 'Rol biriktirish' row: Member = Yo'q; WorkspaceAdmin = Workspace
    ichida; CustomerOwner = Ha (resolves as WORKSPACE_ADMIN — see
    get_workspace_context)."""
    if context.role is not WorkspaceRole.WORKSPACE_ADMIN:
        raise AuthorizationError(Decision.DENY, f"role {context.role.value} may not manage workspace members")


def authorize_archive_workspace(context: WorkspaceContext) -> None:
    if context.role is not WorkspaceRole.WORKSPACE_ADMIN:
        raise AuthorizationError(Decision.DENY, f"role {context.role.value} may not archive this workspace")


def authorize_task_mutation(context: WorkspaceContext, task: Task) -> None:
    """FR-TASK-004: 'Task state faqat authorized actor tomonidan
    o'zgaradi.' The TRD does not further specify who beyond the actor — a
    workspace_admin override (also reachable by a CustomerOwner, who
    resolves as WORKSPACE_ADMIN) is the same pattern already used for R3
    approvals (authorize_consume_approval) and equally defensible here."""
    is_owner = task.owner_id == f"user:{context.user_id}"
    if not is_owner and context.role is not WorkspaceRole.WORKSPACE_ADMIN:
        raise AuthorizationError(Decision.DENY, "only the task owner or a workspace admin may change this task")


def authorize_engage_workspace_kill_switch(context: WorkspaceContext) -> None:
    """10.2 'Kill switch' row: WorkspaceAdmin = Workspace scope. A
    CustomerOwner also passes (resolves as WORKSPACE_ADMIN) — harmless and
    arguably correct: they already have strictly greater power via the
    dedicated customer-scope kill switch, which would take this workspace
    down too."""
    if context.role is not WorkspaceRole.WORKSPACE_ADMIN:
        raise AuthorizationError(Decision.DENY, f"role {context.role.value} may not operate the workspace kill switch")


@dataclasses.dataclass(frozen=True)
class CustomerContext:
    customer_id: uuid.UUID
    user_id: uuid.UUID
    role: CustomerRole


async def get_customer_context(
    session: AsyncSession, *, user_id: uuid.UUID, customer_id: uuid.UUID
) -> CustomerContext:
    """Parallel to get_workspace_context but for customer-scoped actions
    (currently only the customer-level kill switch). Customer has no RLS of
    its own (it's the tenant root — 0001 migration), so this needs no
    bootstrap-index lookup the way workspace resolution does: customer_id
    from the URL directly becomes the tenant_scoped_session GUC.
    """
    customer = await session.get(Customer, customer_id)
    if customer is None:
        raise AuthorizationError(Decision.DENY, "customer not found")

    membership = await session.scalar(
        select(CustomerMembership).where(
            CustomerMembership.customer_id == customer_id, CustomerMembership.user_id == user_id
        )
    )
    if membership is None:
        raise AuthorizationError(Decision.DENY, "no customer membership")

    return CustomerContext(customer_id=customer_id, user_id=user_id, role=CustomerRole(membership.role))


def authorize_engage_customer_kill_switch(context: CustomerContext) -> None:
    """10.2 'Kill switch' row: CustomerOwner = Customer scope."""
    if context.role is not CustomerRole.CUSTOMER_OWNER:
        raise AuthorizationError(Decision.DENY, f"role {context.role.value} may not operate the customer kill switch")


def authorize_view_customer_audit(context: CustomerContext) -> None:
    """10.2 'Audit ko'rish' row: CustomerOwner = 'Customer bo'yicha';
    Auditor = 'Faqat o'qish, to'liq'. A plain Member's access is
    'O'z amallarini' (their own actions) — that is the workspace-scoped
    endpoint (api/audit.py's other route), not this customer-wide one."""
    if context.role not in (CustomerRole.CUSTOMER_OWNER, CustomerRole.AUDITOR):
        raise AuthorizationError(Decision.DENY, f"role {context.role.value} may not view customer-wide audit")
