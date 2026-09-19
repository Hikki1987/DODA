"""Shared declarative base and mixins for all domain modules.

Per CLAUDE.md dependency rules: a domain module may import this shared base,
but never another domain module's models directly — cross-domain references
go through ID/reference columns only (e.g. `customer_id: Mapped[uuid.UUID]`),
never a SQLAlchemy relationship() across domain boundaries.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
