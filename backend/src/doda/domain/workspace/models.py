"""Workspace domain — FR-WKS (workspace half). Root aggregate: Workspace.

Every tenant-scoped table in this domain carries `customer_id` directly
(NFR-ISO-002: no global ID lookup) even though Workspace also has its own id,
so repositories can filter by customer_id without a join.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from doda.domain.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class Workspace(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "workspace_workspaces"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(256))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class WorkspaceMembership(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "workspace_memberships"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    customer_membership_id: Mapped[uuid.UUID] = mapped_column(index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspace_workspaces.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    """Workspace-level role: workspace_admin | member (10.2)."""
