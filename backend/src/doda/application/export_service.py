"""Personal data export — FR-CTL-002 ("ma'lumot eksporti").

v1 is deliberately synchronous: today's data volumes are trivially small
(no Knowledge/RAG files, no chat transcripts — neither domain exists yet),
so a plain request/response export is honestly sufficient. The acceptance
criterion's "asinxron, kuzatiladigan" (async, trackable) half is
intentionally NOT met here — see CLAUDE.md's known limitations — standing
up a generic async job queue before there is real async-sized data to
export would be speculative infrastructure, not a real requirement yet.

Every field returned is the requesting user's own: tasks they own,
notifications addressed to them, audit events where they are the actor.
Never another member's data, even within a workspace they share.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select

from doda.application.audit_query_service import list_audit_events
from doda.application.audit_service import record_audit_event
from doda.application.notification_service import list_notifications_for_user
from doda.application.task_service import list_tasks_for_workspace
from doda.application.workspace_service import MyWorkspaceEntry, list_my_workspaces
from doda.db import async_session_factory, tenant_scoped_session
from doda.domain.audit.models import AuditEvent
from doda.domain.customer.models import UserCustomerIndex
from doda.domain.identity.models import User
from doda.domain.notification.models import Notification
from doda.domain.task.models import Task

EXPORT_PAGE_SIZE = 200


@dataclass
class MyDataExport:
    user_id: uuid.UUID
    display_name: str
    memberships: list[MyWorkspaceEntry] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    notifications: list[Notification] = field(default_factory=list)
    audit_events: list[AuditEvent] = field(default_factory=list)


async def export_my_data(user_id: uuid.UUID, *, trace_id: uuid.UUID) -> MyDataExport:
    """`trace_id` should be the exporting HTTP request's own trace_id
    (NFR-OBS-001 — same lesson as action_service.propose_action: reuse the
    request's trace_id for every audit event this call produces, rather
    than a disconnected uuid4() per write)."""
    memberships = await list_my_workspaces(user_id)

    async with async_session_factory() as db:
        user = await db.get(User, user_id)
        assert user is not None  # a valid session always resolves to a real User
        # Independent of `memberships`: a CustomerOwner of a customer with
        # zero workspaces gets no entries from list_my_workspaces at all
        # (it only ever yields workspace-shaped rows) — deriving the
        # customer scope from `memberships` instead of this index would
        # silently skip that customer's notifications/audit events (and
        # this export's own audit trail) entirely. UserCustomerIndex is the
        # actual "which customers do I belong to" source of truth.
        customer_ids = (
            await db.scalars(
                select(UserCustomerIndex.customer_id).where(UserCustomerIndex.user_id == user_id)
            )
        ).all()

    actor_id = f"user:{user_id}"
    export = MyDataExport(user_id=user_id, display_name=user.display_name, memberships=memberships)

    seen_workspace_ids: set[uuid.UUID] = set()
    for membership in memberships:
        if membership.workspace_id in seen_workspace_ids:
            continue
        seen_workspace_ids.add(membership.workspace_id)

        async with tenant_scoped_session(membership.customer_id) as db:
            workspace_tasks = await list_tasks_for_workspace(
                db, workspace_id=membership.workspace_id, limit=EXPORT_PAGE_SIZE
            )
            export.tasks.extend(task for task in workspace_tasks if task.owner_id == actor_id)

    for customer_id in customer_ids:
        async with tenant_scoped_session(customer_id) as db:
            export.notifications.extend(
                await list_notifications_for_user(
                    db, customer_id=customer_id, recipient_id=actor_id, limit=EXPORT_PAGE_SIZE
                )
            )
            export.audit_events.extend(
                await list_audit_events(
                    db, customer_id=customer_id, actor_id=actor_id, limit=EXPORT_PAGE_SIZE
                )
            )
            # FR-CTL-002 acceptance: "eksport ... kuzatiladigan" — one row
            # per customer touched, matching the multi-tenant-write pattern
            # already used by create_customer_with_owner/invite_customer_member.
            await record_audit_event(
                db,
                customer_id=customer_id,
                trace_id=trace_id,
                actor_id=actor_id,
                event_type="user.data_exported.v1",
                safe_metadata={"scope": "customer"},
            )

    return export
