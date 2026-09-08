"""Audit domain — FR-AUD. Root aggregate: AuditEvent.

Append-only, hash-chained (FR-AUD-004): every row's `hash` covers its own
content plus the previous row's hash within the same customer, so tampering
breaks the chain and is detectable by a verification job. No application
code may UPDATE or DELETE a row in this table — enforce with a DB trigger
or REVOKE in the migration, not just convention.

Payload is deliberately narrow (11.3, FR-AUD-003): no secrets, tokens, PII,
or prompt content — only what is needed to reconstruct "who did what to
what, when, with what outcome".
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from doda.domain.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class AuditEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_events"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(index=True, default=None)
    """Nullable: some events (customer creation, customer-membership
    changes, the customer-scoped kill switch) have no single workspace to
    attach to. A real, indexed column rather than a safe_metadata field —
    FR-AUD-002's 'Audit viewer: filtr' needs to filter by workspace
    efficiently for the WorkspaceAdmin scope (10.2: 'Workspace bo'yicha'),
    which JSON-blob text search could not do correctly or with an index."""
    trace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    actor_id: Mapped[str] = mapped_column(String(256))
    event_type: Mapped[str] = mapped_column(String(128))
    """Versioned taxonomy, e.g. 'action.approved.v1' (11.3)."""
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    safe_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    prev_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    hash: Mapped[str] = mapped_column(String(64))


class AuditChainTip(Base):
    """Serialization point for the per-customer hash chain (FR-AUD-004).
    doda.application.audit_service.record_audit_event locks this single row
    (SELECT ... FOR UPDATE) before computing the next hash, so two
    concurrent writers for the same customer cannot both read the same
    prev_hash and fork the chain. One row per customer, lazily created via
    upsert on first use — never read or written anywhere else.
    """

    __tablename__ = "audit_chain_tips"

    customer_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tip_hash: Mapped[str | None] = mapped_column(String(64), default=None)
