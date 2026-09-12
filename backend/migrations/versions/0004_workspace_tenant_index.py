"""Workspace tenant index — bootstrap table for the RLS chicken-and-egg
problem. See doda.domain.workspace.models.WorkspaceTenantIndex for why this
table exists and deliberately carries no RLS policy.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspace_tenant_index",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_index("ix_workspace_tenant_index_customer_id", "workspace_tenant_index", ["customer_id"])

    # Backfill for any workspace created before this table existed.
    # workspace_workspaces has FORCE ROW LEVEL SECURITY (0001), which binds
    # even the table owner — so a plain SELECT here would see zero rows
    # under whatever GUC state the migration connection happens to have.
    # Toggle FORCE off only for this owner-run backfill, then restore it.
    op.execute("ALTER TABLE workspace_workspaces NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "INSERT INTO workspace_tenant_index (workspace_id, customer_id) "
        "SELECT id, customer_id FROM workspace_workspaces "
        "ON CONFLICT (workspace_id) DO NOTHING"
    )
    op.execute("ALTER TABLE workspace_workspaces FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("workspace_tenant_index")
