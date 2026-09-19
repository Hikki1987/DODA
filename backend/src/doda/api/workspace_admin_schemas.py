import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from doda.domain.security.roles import WorkspaceRole


class AddWorkspaceMemberRequest(BaseModel):
    customer_membership_id: uuid.UUID
    role: WorkspaceRole


class ChangeWorkspaceMemberRoleRequest(BaseModel):
    role: WorkspaceRole


class WorkspaceMembershipOut(BaseModel):
    id: uuid.UUID
    customer_membership_id: uuid.UUID
    workspace_id: uuid.UUID
    role: str


class WorkspaceMemberOut(BaseModel):
    membership_id: uuid.UUID | None
    user_id: uuid.UUID
    display_name: str
    role: str


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    name: str
    archived_at: datetime | None


class SetWorkspaceLanguageRequest(BaseModel):
    language: Literal["UZ", "RU", "EN"] | None = None


class WorkspaceLanguageSettingOut(BaseModel):
    language: str | None
