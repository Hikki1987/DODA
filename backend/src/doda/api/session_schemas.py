import uuid
from datetime import datetime

from pydantic import BaseModel

from doda.domain.identity.models import AuthStrength


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    auth_strength: AuthStrength
    is_current: bool
