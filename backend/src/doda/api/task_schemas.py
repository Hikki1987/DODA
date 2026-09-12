import uuid
from datetime import datetime

from pydantic import BaseModel

from doda.domain.task.models import TaskStatus


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
