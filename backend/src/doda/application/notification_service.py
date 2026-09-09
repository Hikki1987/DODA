"""Notification delivery — FR-NTF-001/002/003. "Delivery" for an in-app
notification is the INSERT itself — the recipient can query it
immediately, there is no separate async delivery step the way there would
be for an email/Telegram adapter (future work, FR-NTF-001). FR-NTF-001's
"Bildirishnoma yetkazilishi audit qilinadi" is satisfied by writing an
audit event in the same transaction as the notification row.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from doda.application.audit_service import record_audit_event
from doda.domain.base import utcnow
from doda.domain.notification.models import Notification, NotificationPreference, NotificationType

# FR-NTF-004: "Security alert'ni o'chirib bo'lmaydi" — the one type
# that must always reach the recipient no matter what preference row
# exists. Enforced here, not as a DB constraint (see the 0009 migration's
# docstring for why), and at both the read and write side below so a
# stray disable can't ever be created in the first place.
_ALWAYS_ON_TYPES = frozenset({NotificationType.SECURITY_ALERT})


class NotificationPreferenceError(Exception):
    """Raised when a caller tries to disable a type that must always fire."""


async def is_notification_type_enabled(
    session: AsyncSession, *, customer_id: uuid.UUID, recipient_id: str, notification_type: NotificationType
) -> bool:
    if notification_type in _ALWAYS_ON_TYPES:
        return True
    preference = await session.scalar(
        select(NotificationPreference).where(
            NotificationPreference.customer_id == customer_id,
            NotificationPreference.recipient_id == recipient_id,
            NotificationPreference.notification_type == notification_type,
        )
    )
    # No row = enabled (the default for every type) — see
    # NotificationPreference's docstring for why a new user needs no rows.
    return preference is None or preference.enabled


async def list_notification_preferences(
    session: AsyncSession, *, customer_id: uuid.UUID, recipient_id: str
) -> dict[NotificationType, bool]:
    """Resolved enabled/disabled for all four types, defaulting to enabled
    where no row exists — a full picture for a preferences UI to render,
    not just the overrides someone has actually saved."""
    rows = await session.execute(
        select(NotificationPreference).where(
            NotificationPreference.customer_id == customer_id,
            NotificationPreference.recipient_id == recipient_id,
        )
    )
    overrides = {row.notification_type: row.enabled for row in rows.scalars()}
    return {t: overrides.get(t, True) for t in NotificationType}


async def set_notification_preference(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    recipient_id: str,
    notification_type: NotificationType,
    enabled: bool,
) -> NotificationPreference:
    if not enabled and notification_type in _ALWAYS_ON_TYPES:
        raise NotificationPreferenceError(f"{notification_type.value} can never be disabled")

    preference = await session.scalar(
        select(NotificationPreference).where(
            NotificationPreference.customer_id == customer_id,
            NotificationPreference.recipient_id == recipient_id,
            NotificationPreference.notification_type == notification_type,
        )
    )
    if preference is None:
        preference = NotificationPreference(
            customer_id=customer_id,
            recipient_id=recipient_id,
            notification_type=notification_type,
            enabled=enabled,
        )
        try:
            async with session.begin_nested():
                session.add(preference)
                await session.flush()
        except IntegrityError:
            # Two requests setting the same (customer, recipient, type)
            # preference at once (a double-click, or the same person on
            # two devices) both saw preference=None and both tried to
            # insert — uq_notification_preferences_scope (0009-migration)
            # is the actual race-safe guard. Unlike the kill-switch engage
            # race, this is a "set X" operation, not "ensure true": each
            # caller has its own intended value, so the recovery re-fetches
            # the row the other request just committed and applies THIS
            # caller's value to it (last write wins) rather than silently
            # keeping the other caller's value.
            preference = await session.scalar(
                select(NotificationPreference).where(
                    NotificationPreference.customer_id == customer_id,
                    NotificationPreference.recipient_id == recipient_id,
                    NotificationPreference.notification_type == notification_type,
                )
            )
            assert preference is not None
            preference.enabled = enabled
            await session.flush()
    else:
        preference.enabled = enabled
        await session.flush()
    return preference


async def create_notification(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    recipient_id: str,
    notification_type: NotificationType,
    reference_type: str,
    reference_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
    safe_metadata: dict[str, Any] | None = None,
) -> Notification | None:
    """Returns None (no row created, no audit event) when the recipient
    has turned this notification_type off (FR-NTF-004) — every existing
    caller (action_service, task_service, kill_switch_service) already
    ignores this function's return value, so the preference check lives
    here once rather than needing a check before each call site."""
    if not await is_notification_type_enabled(
        session, customer_id=customer_id, recipient_id=recipient_id, notification_type=notification_type
    ):
        return None

    notification = Notification(
        customer_id=customer_id,
        workspace_id=workspace_id,
        recipient_id=recipient_id,
        notification_type=notification_type,
        reference_type=reference_type,
        reference_id=reference_id,
        safe_metadata=safe_metadata or {},
    )
    session.add(notification)
    await session.flush()
    await record_audit_event(
        session,
        customer_id=customer_id,
        workspace_id=workspace_id,
        trace_id=uuid.uuid4(),
        actor_id="system:notifier",
        event_type="notification.delivered.v1",
        safe_metadata={
            "notification_id": str(notification.id),
            "recipient_id": recipient_id,
            "notification_type": notification_type.value,
            "reference_type": reference_type,
            "reference_id": str(reference_id),
        },
    )
    return notification


async def list_notifications_for_user(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    recipient_id: str,
    workspace_id: uuid.UUID | None = None,
    unread_only: bool = False,
    limit: int = 50,
) -> list[Notification]:
    """`workspace_id`, when given, matches that workspace OR customer-wide
    notifications (workspace_id IS NULL, e.g. a customer-level
    SECURITY_ALERT) — filtered in SQL, not after fetching, so `limit`
    still caps the right query and a multi-workspace user's other
    workspace's notifications can't crowd out this page's results."""
    query = select(Notification).where(
        Notification.customer_id == customer_id, Notification.recipient_id == recipient_id
    )
    if workspace_id is not None:
        query = query.where(
            (Notification.workspace_id == workspace_id) | (Notification.workspace_id.is_(None))
        )
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    query = query.order_by(Notification.created_at.desc()).limit(min(limit, 200))
    result = await session.execute(query)
    return list(result.scalars())


async def mark_notification_read(session: AsyncSession, notification: Notification) -> Notification:
    if notification.read_at is None:
        notification.read_at = utcnow()
        await session.flush()
    return notification
