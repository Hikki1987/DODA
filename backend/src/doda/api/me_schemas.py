import uuid

from pydantic import BaseModel


class MyWorkspaceOut(BaseModel):
    customer_id: uuid.UUID
    customer_name: str
    workspace_id: uuid.UUID
    workspace_name: str
    role: str
