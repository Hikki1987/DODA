import uuid

from pydantic import BaseModel

from doda.api.audit_schemas import AuditEventOut
from doda.api.notification_schemas import NotificationOut
from doda.api.task_schemas import TaskOut


class MyWorkspaceOut(BaseModel):
    customer_id: uuid.UUID
    customer_name: str
    workspace_id: uuid.UUID
    workspace_name: str
    role: str


class MyDataExportOut(BaseModel):
    user_id: uuid.UUID
    display_name: str
    memberships: list[MyWorkspaceOut]
    tasks: list[TaskOut]
    notifications: list[NotificationOut]
    audit_events: list[AuditEventOut]
