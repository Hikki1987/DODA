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


class AuditChainViolationOut(BaseModel):
    event_id: uuid.UUID
    reason: str


class AuditChainVerificationOut(BaseModel):
    ok: bool
    checked_count: int
    violations: list[AuditChainViolationOut]


class EvidenceEventOut(BaseModel):
    id: uuid.UUID
    event_type: str
    actor_id: str
    workspace_id: uuid.UUID | None
    occurred_at: datetime
    safe_metadata: dict[str, Any]
    prev_hash: str | None
    hash: str
    hash_self_consistent: bool


class EvidencePackageOut(BaseModel):
    customer_id: uuid.UUID
    trace_id: uuid.UUID
    events: list[EvidenceEventOut]
    full_chain_verification: AuditChainVerificationOut
