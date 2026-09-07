"""Transactional outbox — ADR-003, FR-ACT-008.

A row here must be INSERTed in the *same* DB transaction as the domain
change it announces (e.g. Action -> READY), never after a commit — that is
what makes the state change atomic with the promise to eventually cause a
side effect. A separate relay (doda.infrastructure.outbox_relay) polls
unpublished rows and hands them to a transport; it never mutates domain
tables itself.

Deliberately not tenant-RLS-scoped: the relay is a platform-level process
that must see every customer's pending messages to deliver them. The
payload here is already-derived event data (ids, event type), not raw
tenant content, so this is a narrower exposure than a domain table would be.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from doda.domain.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class OutboxMessage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "outbox_messages"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    aggregate_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(index=True)
    event_type: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, index=True)
