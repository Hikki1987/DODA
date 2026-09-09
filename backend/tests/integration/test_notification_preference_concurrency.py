"""Proves set_notification_preference survives two concurrent calls for
the same (customer, recipient, notification_type) — e.g. a double-click,
or the same person toggling the preference from two devices at once —
without a raw IntegrityError reaching the caller.

uq_notification_preferences_scope (0009-migration) already prevents a
genuine duplicate row; the gap was purely the unhandled IntegrityError
on the losing call. Unlike the kill-switch engage race (where both
callers want the same end state), this is a "set X" operation where each
caller may intend a different value — the fix applies each caller's own
intended value to the row rather than silently keeping whichever commits
first.
"""

import asyncio
import uuid

from sqlalchemy import select

from doda.application.notification_service import set_notification_preference
from doda.db import tenant_scoped_session
from doda.domain.notification.models import NotificationPreference, NotificationType


async def test_two_concurrent_sets_for_the_same_preference_both_succeed(db_available: bool) -> None:
    customer_id = uuid.uuid4()
    recipient_id = "user:racer"

    cm1 = tenant_scoped_session(customer_id)
    cm2 = tenant_scoped_session(customer_id)
    session1 = await cm1.__aenter__()
    session2 = await cm2.__aenter__()

    async def toggle(cm, session, enabled):
        preference = await set_notification_preference(
            session,
            customer_id=customer_id,
            recipient_id=recipient_id,
            notification_type=NotificationType.FAILED_ACTION,
            enabled=enabled,
        )
        await cm.__aexit__(None, None, None)
        return preference.enabled

    # Neither call raises — no IntegrityError reaches the caller.
    reported = await asyncio.gather(
        toggle(cm1, session1, False),
        toggle(cm2, session2, True),
    )
    assert reported == [False, True]  # each call reports its own intended value

    async with tenant_scoped_session(customer_id) as session:
        rows = (
            (
                await session.execute(
                    select(NotificationPreference).where(
                        NotificationPreference.customer_id == customer_id,
                        NotificationPreference.recipient_id == recipient_id,
                        NotificationPreference.notification_type == NotificationType.FAILED_ACTION,
                    )
                )
            )
            .scalars()
            .all()
        )

    # Exactly one row — the unique constraint's intent — not two.
    assert len(rows) == 1
