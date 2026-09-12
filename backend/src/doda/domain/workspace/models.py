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


class WorkspaceTenantIndex(Base):
    """Deliberately NOT RLS-protected. Solves a chicken-and-egg problem: an
    API request arrives knowing only a workspace_id (from the URL) and a
    session (proving *who*, not *which tenant*) — but Workspace itself has
    FORCE ROW LEVEL SECURITY, so reading it to learn its customer_id
    requires already knowing that customer_id. This table carries nothing
    but the id mapping, so exposing it costs no tenant content, and lets
    doda.application.authz_service.get_workspace_context open the correctly
    scoped tenant_scoped_session before touching anything else.

    Written only by doda.application.workspace_service.create_workspace, in
    the same transaction as the Workspace row it mirrors — never written to
    directly, so it cannot drift from the source of truth.
    """

    __tablename__ = "workspace_tenant_index"

    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
