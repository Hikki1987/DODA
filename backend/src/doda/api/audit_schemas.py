import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    workspace_id: uuid.UUID | None
    trace_id: uuid.UUID
    actor_id: str
    event_type: str
    occurred_at: datetime
    safe_metadata: dict[str, Any]
    prev_hash: str | None
    hash: str
