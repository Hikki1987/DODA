"""Pydantic request/response models for the Experience layer (6.1). Kept
separate from domain models — the public API contract must be able to
evolve independently of internal aggregates (11.2: contracts are
versioned)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from doda.domain.action.approval import ApprovalStatus
from doda.domain.action.models import ActionStatus, RiskLevel


class ProposeActionRequest(BaseModel):
    tool_name: str
    risk_level: RiskLevel
    payload: dict[str, Any]
    task_id: uuid.UUID | None = None


class ApprovalOut(BaseModel):
    id: uuid.UUID
    status: ApprovalStatus
    expires_at: datetime
    nonce: str
    """Returned once, to the same caller who is shown the pending-approval
    preview — a one-time credential for approving this specific action, so
    it must never be logged (12.3) beyond this response."""


class ActionOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    trace_id: uuid.UUID
    tool_name: str
    risk_level: RiskLevel
    status: ActionStatus
    payload: dict[str, Any]


class SubmitActionResponse(BaseModel):
    action: ActionOut
    approval: ApprovalOut | None = None


class ConsumeApprovalRequest(BaseModel):
    nonce: str
