import uuid
from datetime import datetime

from pydantic import BaseModel

from doda.domain.task.models import ReminderStatus, TaskStatus


class CreateTaskRequest(BaseModel):
    title: str
    due_date: datetime | None = None
    parent_task_id: uuid.UUID | None = None


class ChangeTaskStatusRequest(BaseModel):
    target_status: TaskStatus


class TaskOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    owner_id: str
    title: str
    status: TaskStatus
    due_date: datetime | None
    parent_task_id: uuid.UUID | None


class TaskHistoryEntryOut(BaseModel):
    id: uuid.UUID
    actor_id: str
    from_status: TaskStatus | None
    to_status: TaskStatus
    created_at: datetime


class RecordTaskDecisionRequest(BaseModel):
    variant: str
    tradeoff: str
    decision: str
    reason: str


class TaskDecisionOut(BaseModel):
    id: uuid.UUID
    actor_id: str
    variant: str
    tradeoff: str
    decision: str
    reason: str
    created_at: datetime


class AttachDocumentRequest(BaseModel):
    document_id: uuid.UUID


class TaskAttachmentOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    attached_by: str
    created_at: datetime
    broken: bool
    """FR-TASK-006's own acceptance criterion: true once the linked
    document has been deleted — the link stays visible, it is never
    silently dropped or turned into an error."""
    filename: str | None
    content_type: str | None
    size_bytes: int | None


class RequestReminderRequest(BaseModel):
    remind_at: datetime


class ConfirmReminderRequest(BaseModel):
    remind_at: datetime
    """Echoes the exact value being confirmed (FR-TASK-005: the TIME
    itself is what's confirmed) — must match the reminder's current
    remind_at or the request is rejected as a mismatch."""


class ReminderOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    actor_id: str
    remind_at: datetime
    status: ReminderStatus
    confirmed_at: datetime | None
    fired_at: datetime | None
    created_at: datetime
