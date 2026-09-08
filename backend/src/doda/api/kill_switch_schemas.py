from pydantic import BaseModel


class EngageKillSwitchRequest(BaseModel):
    reason: str


class KillSwitchStatusOut(BaseModel):
    engaged: bool
