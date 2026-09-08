"""Kill switch — FR-CTL-003. `assert_not_killed` is called at the very top
of doda.application.action_service.propose_action, so an engaged switch
blocks every NEW action from that point on — in-flight actions already
past propose are not torn down (FR-CTL-003's acceptance criterion is about
blocking new actions, not force-cancelling running ones; that is FR-CTL-005
undo, a separate, Should-priority concern).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doda.application.audit_service import record_audit_event
from doda.application.notification_service import create_notification
from doda.domain.base import utcnow
from doda.domain.customer.models import CustomerMembership
from doda.domain.notification.models import NotificationType
from doda.domain.security.kill_switch import CustomerKillSwitch, WorkspaceKillSwitch
from doda.domain.workspace.models import WorkspaceMembership


class KillSwitchEngagedError(Exception):
    def __init__(self, scope: str) -> None:
        self.scope = scope
        super().__init__(f"kill switch engaged at {scope} scope")


async def assert_not_killed(
    session: AsyncSession, *, customer_id: uuid.UUID, workspace_id: uuid.UUID
) -> None:
    if await session.get(CustomerKillSwitch, customer_id) is not None:
        raise KillSwitchEngagedError("customer")
    if await session.get(WorkspaceKillSwitch, workspace_id) is not None:
        raise KillSwitchEngagedError("workspace")


async def engage_workspace_kill_switch(
    session: AsyncSession, *, workspace_id: uuid.UUID, customer_id: uuid.UUID, actor_id: str, reason: str
) -> WorkspaceKillSwitch:
    switch = await session.get(WorkspaceKillSwitch, workspace_id)
    if switch is None:
        switch = WorkspaceKillSwitch(
            workspace_id=workspace_id,
            customer_id=customer_id,
            engaged_at=utcnow(),
            engaged_by=actor_id,
            reason=reason,
        )
        session.add(switch)
        await session.flush()
        await record_audit_event(
            session,
            customer_id=customer_id,
            workspace_id=workspace_id,
            trace_id=uuid.uuid4(),
            actor_id=actor_id,
            event_type="killswitch.workspace.engaged.v1",
            safe_metadata={"workspace_id": str(workspace_id), "reason": reason},
        )
        # FR-NTF-002 SECURITY_ALERT: every member of the affected workspace,
        # not just whoever engaged it — this is exactly the kind of event
        # FR-NTF-004 says can never be silenced.
        member_user_ids = (
            await session.execute(
                select(CustomerMembership.user_id)
                .join(WorkspaceMembership, WorkspaceMembership.customer_membership_id == CustomerMembership.id)
                .where(WorkspaceMembership.workspace_id == workspace_id)
            )
        ).scalars()
        for user_id in member_user_ids:
            await create_notification(
                session,
                customer_id=customer_id,
                workspace_id=workspace_id,
                recipient_id=f"user:{user_id}",
                notification_type=NotificationType.SECURITY_ALERT,
                reference_type="workspace_kill_switch",
                reference_id=switch.workspace_id,
                safe_metadata={"scope": "workspace", "reason": reason},
            )
    return switch


async def disengage_workspace_kill_switch(
    session: AsyncSession, *, workspace_id: uuid.UUID, customer_id: uuid.UUID, actor_id: str
) -> None:
    switch = await session.get(WorkspaceKillSwitch, workspace_id)
    if switch is not None:
        await session.delete(switch)
        await session.flush()
        await record_audit_event(
            session,
            customer_id=customer_id,
            workspace_id=workspace_id,
            trace_id=uuid.uuid4(),
            actor_id=actor_id,
            event_type="killswitch.workspace.disengaged.v1",
            safe_metadata={"workspace_id": str(workspace_id)},
        )


async def engage_customer_kill_switch(
    session: AsyncSession, *, customer_id: uuid.UUID, actor_id: str, reason: str
) -> CustomerKillSwitch:
    switch = await session.get(CustomerKillSwitch, customer_id)
    if switch is None:
        switch = CustomerKillSwitch(
            customer_id=customer_id, engaged_at=utcnow(), engaged_by=actor_id, reason=reason
        )
        session.add(switch)
        await session.flush()
        await record_audit_event(
            session,
            customer_id=customer_id,
            trace_id=uuid.uuid4(),
            actor_id=actor_id,
            event_type="killswitch.customer.engaged.v1",
            safe_metadata={"reason": reason},
        )
        member_user_ids = (
            await session.execute(
                select(CustomerMembership.user_id).where(CustomerMembership.customer_id == customer_id)
            )
        ).scalars()
        for user_id in member_user_ids:
            await create_notification(
                session,
                customer_id=customer_id,
                recipient_id=f"user:{user_id}",
                notification_type=NotificationType.SECURITY_ALERT,
                reference_type="customer_kill_switch",
                reference_id=customer_id,
                safe_metadata={"scope": "customer", "reason": reason},
            )
    return switch


async def disengage_customer_kill_switch(
    session: AsyncSession, *, customer_id: uuid.UUID, actor_id: str
) -> None:
    switch = await session.get(CustomerKillSwitch, customer_id)
    if switch is not None:
        await session.delete(switch)
        await session.flush()
        await record_audit_event(
            session,
            customer_id=customer_id,
            trace_id=uuid.uuid4(),
            actor_id=actor_id,
            event_type="killswitch.customer.disengaged.v1",
            safe_metadata={},
        )
