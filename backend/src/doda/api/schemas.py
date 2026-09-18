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
    preview: str
    """FR-ACT-002: a human-readable dry-run description of what this
    action will do (what/where/to whom/what change), shown for every
    action regardless of risk_level — cheap to compute, and there's no
    reason to withhold it below R3 (see `describe_action_preview`)."""


class SubmitActionResponse(BaseModel):
    action: ActionOut
    approval: ApprovalOut | None = None


class ConsumeApprovalRequest(BaseModel):
    nonce: str


class CompleteCompensationRequest(BaseModel):
    outcome: ActionStatus
    """FR-ACT-009: must be COMPENSATED (the reversal was carried out) or
    FAILED (it could not be) — a human's attestation, not a system
    verification; see application.action_service.complete_compensation's
    own docstring for why there is nothing automated to check here."""
