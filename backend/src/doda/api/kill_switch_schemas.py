from datetime import datetime

from pydantic import BaseModel


class EngageKillSwitchRequest(BaseModel):
    reason: str


class KillSwitchStatusOut(BaseModel):
    engaged: bool
    reason: str | None = None
    engaged_at: datetime | None = None
    engaged_by: str | None = None
