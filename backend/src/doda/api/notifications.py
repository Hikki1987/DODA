"""Notification endpoints — FR-NTF. The workspace-scoped pair below is the
original surface; the customer-scoped pair covers what CLAUDE.md flagged
as a known gap: a member of several workspaces under the same customer
had no single place to see notifications from all of them at once.
list_notifications_for_user already returns every notification for a
(customer_id, recipient_id) when called with no workspace_id filter — the
gap was purely a missing HTTP endpoint, not missing application logic.

A true cross-*customer* inbox (spanning customers, not just workspaces)
is deliberately not attempted here: customer_memberships is itself RLS-
scoped by customer_id (0001), so "which customers does this user belong
to" cannot be answered without already knowing a customer_id to scope
the lookup by — the same bootstrap problem workspace_tenant_index exists
to solve, one level up. Solving that would mean introducing a second,
deliberately non-RLS bootstrap table (a real architectural decision, not
a routine endpoint addition) — left for a future change request rather
than folded into this feature silently.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from doda.api.dependencies import (
    CustomerRequestContext,
    RequestContext,
    get_customer_request_context,
    get_request_context,
)
from doda.api.notification_schemas import (
    NotificationOut,
    NotificationPreferenceOut,
    SetNotificationPreferenceRequest,
)
from doda.application.notification_service import (
    list_notification_preferences,
    list_notifications_for_user,
    mark_notification_read,
    set_notification_preference,
)
from doda.domain.notification.models import Notification, NotificationType

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


@router.get(
    "/v1/customers/{customer_id}/notification-preferences",
    response_model=list[NotificationPreferenceOut],
)
async def list_my_notification_preferences(
    ctx: CustomerRequestContext = Depends(get_customer_request_context),
) -> list[NotificationPreferenceOut]:
    """Customer-scoped, not workspace-scoped: "do I want this TYPE of
    notification at all" is one setting per person per customer, the same
    granularity notification_preferences is stored at — not per-workspace."""
    resolved = await list_notification_preferences(
        ctx.db, customer_id=ctx.customer.customer_id, recipient_id=f"user:{ctx.customer.user_id}"
    )
    return [
        NotificationPreferenceOut(notification_type=t, enabled=enabled) for t, enabled in resolved.items()
    ]


@router.put(
    "/v1/customers/{customer_id}/notification-preferences/{notification_type}",
    response_model=NotificationPreferenceOut,
)
async def set_my_notification_preference(
    notification_type: NotificationType,
    body: SetNotificationPreferenceRequest,
    ctx: CustomerRequestContext = Depends(get_customer_request_context),
) -> NotificationPreferenceOut:
    preference = await set_notification_preference(
        ctx.db,
        customer_id=ctx.customer.customer_id,
        recipient_id=f"user:{ctx.customer.user_id}",
        notification_type=notification_type,
        enabled=body.enabled,
    )
    return NotificationPreferenceOut(
        notification_type=preference.notification_type, enabled=preference.enabled
    )


@router.get("/v1/customers/{customer_id}/notifications", response_model=list[NotificationOut])
async def list_my_notifications_across_workspaces(
    unread_only: bool = False,
    limit: int = Query(default=50, le=200),
    ctx: CustomerRequestContext = Depends(get_customer_request_context),
) -> list[NotificationOut]:
    """No role check beyond customer membership: this is always "my own"
    notifications (recipient_id pinned to the caller), never someone
    else's, so — unlike the audit viewer — every role may call it."""
    notifications = await list_notifications_for_user(
        ctx.db,
        customer_id=ctx.customer.customer_id,
        recipient_id=f"user:{ctx.customer.user_id}",
        unread_only=unread_only,
        limit=limit,
    )
    return [_to_out(n) for n in notifications]


@router.post(
    "/v1/customers/{customer_id}/notifications/{notification_id}/read",
    response_model=NotificationOut,
)
async def mark_read_across_workspaces(
    notification_id: uuid.UUID, ctx: CustomerRequestContext = Depends(get_customer_request_context)
) -> NotificationOut:
    notification = await ctx.db.get(Notification, notification_id)
    if notification is None or notification.recipient_id != f"user:{ctx.customer.user_id}":
        raise HTTPException(status_code=404, detail="notification not found")

    notification = await mark_notification_read(ctx.db, notification)
    return _to_out(notification)
