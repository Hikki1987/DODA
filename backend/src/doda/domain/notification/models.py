"""Notification domain — FR-NTF. In-app only for v1 (FR-NTF-001: "email/
Telegram keyingi adapter" is future work). Deliberately carries no
free-text message field — FR-NTF-003 ("Bildirishnoma matnida sezgir
kontent bo'lmaydi... faqat havola va safe metadata") is enforced by the
schema itself: a notification is a pointer (reference_type + reference_id)
plus a narrow safe_metadata blob, never the underlying content (an
action's payload, a task's full detail, etc).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from doda.domain.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class NotificationType(enum.StrEnum):
    """FR-NTF-002's four required types."""

    PENDING_APPROVAL = "PENDING_APPROVAL"
    FAILED_ACTION = "FAILED_ACTION"
    COMPLETED_TASK = "COMPLETED_TASK"
    SECURITY_ALERT = "SECURITY_ALERT"


class Notification(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "notifications"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(index=True, default=None)
    recipient_id: Mapped[str] = mapped_column(String(256), index=True)
    """Same "user:{uuid}" convention as Action.actor_id / Task.owner_id."""
    notification_type: Mapped[NotificationType] = mapped_column(
        SAEnum(NotificationType, name="notification_type", native_enum=False, length=32)
    )
    reference_type: Mapped[str] = mapped_column(String(64))
    """What this notification is about, e.g. "action", "task" — the client
    uses (reference_type, reference_id) to link to the real resource."""
    reference_id: Mapped[uuid.UUID] = mapped_column()
    safe_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class NotificationPreference(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """FR-NTF-004: a recipient may turn off a notification type — except
    SECURITY_ALERT, which stays mandatory (10.2/12.4: kill switch and
    other security alerts must always reach every member). Absence of a
    row means "enabled" (the default for all four types); a row only
    exists once someone has changed it away from the default, so a new
    user needs no rows seeded at all."""

    __tablename__ = "notification_preferences"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    recipient_id: Mapped[str] = mapped_column(String(256), index=True)
    notification_type: Mapped[NotificationType] = mapped_column(
        SAEnum(NotificationType, name="notification_preference_type", native_enum=False, length=32)
    )
    enabled: Mapped[bool] = mapped_column(default=True)
