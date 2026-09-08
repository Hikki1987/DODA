"""Action domain — FR-ACT. Root aggregate: Action.

`status` is the authoritative state machine from TRD section 4.2. It must
never be assigned directly — always go through
`doda.domain.action.state_machine.transition()` via the application layer
(doda.application.action_service), so an illegal transition raises instead
of silently corrupting state, and every change gets audited.

`idempotency_key` is unique per customer (FR-ACT-004): a duplicate propose
call with the same key must return the existing Action, never create a
second one — see doda.application.action_service.propose_action.
"""

import enum
import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from doda.domain.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class RiskLevel(enum.StrEnum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"


# R0-R2: policy-only, no human approval (9.1). R3+: preview + approval required.
AUTO_APPROVED_RISK_LEVELS = frozenset({RiskLevel.R0, RiskLevel.R1, RiskLevel.R2})


class ActionStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    DENIED = "DENIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class Action(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "action_actions"
    __table_args__ = (
        UniqueConstraint("customer_id", "idempotency_key", name="uq_action_customer_idempotency_key"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    trace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    actor_id: Mapped[str] = mapped_column(String(256))
    tool_name: Mapped[str] = mapped_column(String(128))
    risk_level: Mapped[RiskLevel] = mapped_column(
        SAEnum(RiskLevel, name="risk_level", native_enum=False, length=2)
    )
    payload: Mapped[dict] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    """sha256 of the canonical payload — see doda.application.hashing.hash_payload.
    Approval binds to this value (9.2); if payload changes, the hash changes
    and any prior approval becomes invalid by construction."""
    idempotency_key: Mapped[str] = mapped_column(String(256))
    status: Mapped[ActionStatus] = mapped_column(
        SAEnum(ActionStatus, name="action_status", native_enum=False, length=32),
        default=ActionStatus.DRAFT,
    )
