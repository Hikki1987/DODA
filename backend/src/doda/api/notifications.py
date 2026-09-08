"""Notification endpoints — FR-NTF. Workspace-scoped like the rest of this
API (see CLAUDE.md known limitations: a true cross-workspace "my
notifications" inbox would need a session-scoped, not workspace-scoped,
endpoint — deferred, not built here).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from doda.api.dependencies import RequestContext, get_request_context
from doda.api.notification_schemas import NotificationOut
from doda.application.notification_service import (
    list_notifications_for_user,
    mark_notification_read,
)
from doda.domain.notification.models import Notification

router = APIRouter(tags=["notifications"])


def _to_out(notification: Notification) -> NotificationOut:
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


@router.get("/v1/workspaces/{workspace_id}/notifications", response_model=list[NotificationOut])
async def list_my_notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, le=200),
    ctx: RequestContext = Depends(get_request_context),
) -> list[NotificationOut]:
    notifications = await list_notifications_for_user(
        ctx.db,
        customer_id=ctx.workspace.customer_id,
        recipient_id=f"user:{ctx.workspace.user_id}",
        workspace_id=ctx.workspace.workspace_id,
        unread_only=unread_only,
        limit=limit,
    )
    return [_to_out(n) for n in notifications]


@router.post(
    "/v1/workspaces/{workspace_id}/notifications/{notification_id}/read",
    response_model=NotificationOut,
)
async def mark_read(
    notification_id: uuid.UUID, ctx: RequestContext = Depends(get_request_context)
) -> NotificationOut:
    notification = await ctx.db.get(Notification, notification_id)
    if notification is None or notification.recipient_id != f"user:{ctx.workspace.user_id}":
        # Not-found, not denied: a notification's existence for someone
        # else is not something to confirm (10.1).
        raise HTTPException(status_code=404, detail="notification not found")

    notification = await mark_notification_read(ctx.db, notification)
    return _to_out(notification)
