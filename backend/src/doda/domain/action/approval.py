"""Approval domain — section 9.2 invariants. Belongs to the Action bounded
context (not a separate top-level domain): an Approval only ever exists to
gate one Action and is meaningless without it.

Invariants enforced by the application layer, not by this model alone
(see doda.application.action_service.consume_approval):
- bound to the action's payload_hash at creation time — if the payload
  changes afterward, the stored hash no longer matches and the approval
  must be treated as void;
- time-limited (`expires_at`, default 10 minutes) and one-time (`nonce`);
- "doim ruxsat berish" (standing approval) does not exist — every approval
  is scoped to exactly one action.
"""

import enum
import uuid
from datetime import datetime, timedelta

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from doda.domain.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

DEFAULT_APPROVAL_TTL = timedelta(minutes=10)


class ApprovalStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class Approval(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "action_approvals"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("action_actions.id"), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    approver_id: Mapped[str | None] = mapped_column(String(256), default=None)
    nonce: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[ApprovalStatus] = mapped_column(
        SAEnum(ApprovalStatus, name="approval_status", native_enum=False, length=16),
        default=ApprovalStatus.PENDING,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
