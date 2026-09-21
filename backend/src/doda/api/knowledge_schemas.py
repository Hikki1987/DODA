import uuid
from datetime import datetime

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    uploader_id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime
