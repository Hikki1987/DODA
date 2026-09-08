"""Who am I, what do I have access to" — session-scoped, not workspace-
or customer-scoped, matching api/sessions.py's pattern. Every other
endpoint in this API requires the caller to already know a workspace_id or
customer_id up front; this is the one entry point a client can call right
after login with nothing but a session.
"""

import uuid

from fastapi import APIRouter, Depends, Request

from doda.api.audit_schemas import AuditEventOut
from doda.api.dependencies import CurrentIdentity, get_current_identity
from doda.api.me_schemas import MyDataExportOut, MyWorkspaceOut
from doda.api.notification_schemas import NotificationOut
from doda.api.task_schemas import TaskOut
from doda.application.export_service import export_my_data
from doda.application.workspace_service import list_my_workspaces
from doda.domain.audit.models import AuditEvent
from doda.domain.notification.models import Notification
from doda.domain.task.models import Task

router = APIRouter(tags=["me"])


@router.get("/v1/me/workspaces", response_model=list[MyWorkspaceOut])
async def list_my_workspaces_endpoint(
    identity: CurrentIdentity = Depends(get_current_identity),
) -> list[MyWorkspaceOut]:
    entries = await list_my_workspaces(identity.user_id)
    return [
        MyWorkspaceOut(
            customer_id=entry.customer_id,
            customer_name=entry.customer_name,
            workspace_id=entry.workspace_id,
            workspace_name=entry.workspace_name,
            role=entry.role,
        )
        for entry in entries
    ]


def _task_out(task: Task) -> TaskOut:
    return TaskOut(
        id=task.id,
        workspace_id=task.workspace_id,
        owner_id=task.owner_id,
        title=task.title,
        status=task.status,
        due_date=task.due_date,
        parent_task_id=task.parent_task_id,
    )


def _notification_out(notification: Notification) -> NotificationOut:
    return NotificationOut(
        id=notification.id,
        workspace_id=notification.workspace_id,
        notification_type=notification.notification_type,
        reference_type=notification.reference_type,
        reference_id=notification.reference_id,
        safe_metadata=notification.safe_metadata,
        created_at=notification.created_at,
        read_at=notification.read_at,
    )


def _audit_event_out(event: AuditEvent) -> AuditEventOut:
    return AuditEventOut(
        id=event.id,
        customer_id=event.customer_id,
        workspace_id=event.workspace_id,
        trace_id=event.trace_id,
        actor_id=event.actor_id,
        event_type=event.event_type,
        occurred_at=event.occurred_at,
        safe_metadata=event.safe_metadata,
        prev_hash=event.prev_hash,
        hash=event.hash,
    )


@router.get("/v1/me/export", response_model=MyDataExportOut)
async def export_my_data_endpoint(
    request: Request,
    identity: CurrentIdentity = Depends(get_current_identity),
) -> MyDataExportOut:
    """FR-CTL-002 ("ma'lumot eksporti") — everything the caller owns across
    every customer/workspace they belong to, in one response. See
    application/export_service.py for why this is synchronous in v1.
    """
    export = await export_my_data(identity.user_id, trace_id=uuid.UUID(request.state.trace_id))
    return MyDataExportOut(
        user_id=export.user_id,
        display_name=export.display_name,
        memberships=[
            MyWorkspaceOut(
                customer_id=m.customer_id,
                customer_name=m.customer_name,
                workspace_id=m.workspace_id,
                workspace_name=m.workspace_name,
                role=m.role,
            )
            for m in export.memberships
        ],
        tasks=[_task_out(t) for t in export.tasks],
        notifications=[_notification_out(n) for n in export.notifications],
        audit_events=[_audit_event_out(e) for e in export.audit_events],
    )
