"""Add nullable workspace_id to audit_events — needed for FR-AUD-002's
audit viewer to filter by workspace efficiently (10.2: WorkspaceAdmin sees
audit "Workspace bo'yicha"). Nullable because customer-scoped-only events
(customer creation/membership changes, the customer-level kill switch)
have no single workspace to attach to.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_audit_events_workspace_id", "audit_events", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_workspace_id", table_name="audit_events")
    op.drop_column("audit_events", "workspace_id")
