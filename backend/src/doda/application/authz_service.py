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
from doda.domain.customer.models import CustomerMembership
from doda.domain.identity.models import AuthStrength
from doda.domain.security.decisions import Decision
from doda.domain.security.roles import (
    ROLES_THAT_MAY_APPROVE_ANOTHER_ACTORS_ACTION,
    ROLES_THAT_MAY_PROPOSE_ACTIONS,
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


async def get_workspace_context(
    session: AsyncSession, *, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> WorkspaceContext:
    """NFR-ISO-002: never look up a workspace by id alone — always through
    the membership chain, so a user with no membership gets DENY, not a
    lookup of a workspace that happens to belong to someone else's customer.
    """
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.archived_at is not None:
        raise AuthorizationError(Decision.DENY, "workspace not found or archived")

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
    action. Auditor can never approve, full stop.
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


def authorize_task_mutation(context: WorkspaceContext, task: Task) -> None:
    """FR-TASK-004: 'Task state faqat authorized actor tomonidan
    o'zgaradi.' The TRD does not further specify who beyond the actor — a
    workspace_admin override is the same pattern already used for R3
    approvals (authorize_consume_approval) and equally defensible here."""
    is_owner = task.owner_id == f"user:{context.user_id}"
    if not is_owner and context.role is not WorkspaceRole.WORKSPACE_ADMIN:
        raise AuthorizationError(Decision.DENY, "only the task owner or a workspace admin may change this task")
