import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from doda.domain.notification.models import NotificationType


class NotificationOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID | None
    notification_type: NotificationType
    reference_type: str
    reference_id: uuid.UUID
    safe_metadata: dict[str, Any]
    created_at: datetime
    read_at: datetime | None


class NotificationPreferenceOut(BaseModel):
    notification_type: NotificationType
    enabled: bool


class SetNotificationPreferenceRequest(BaseModel):
    enabled: bool
