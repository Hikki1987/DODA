"""Kill switch tables — FR-CTL-003. A row's existence means "engaged"; see
doda.domain.security.kill_switch's module docstring for the scope
decisions (workspace + customer, no global/platform scope yet).

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspace_kill_switches",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("engaged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("engaged_by", sa.String(256), nullable=False),
        sa.Column("reason", sa.String(512), nullable=False),
    )
    op.create_index("ix_workspace_kill_switches_customer_id", "workspace_kill_switches", ["customer_id"])
    op.execute("ALTER TABLE workspace_kill_switches ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE workspace_kill_switches FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON workspace_kill_switches
        USING (customer_id = current_setting('app.current_customer_id', true)::uuid)
        WITH CHECK (customer_id = current_setting('app.current_customer_id', true)::uuid)
        """
    )

    op.create_table(
        "customer_kill_switches",
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engaged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("engaged_by", sa.String(256), nullable=False),
        sa.Column("reason", sa.String(512), nullable=False),
    )
    op.execute("ALTER TABLE customer_kill_switches ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE customer_kill_switches FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON customer_kill_switches
        USING (customer_id = current_setting('app.current_customer_id', true)::uuid)
        WITH CHECK (customer_id = current_setting('app.current_customer_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON customer_kill_switches")
    op.drop_table("customer_kill_switches")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON workspace_kill_switches")
    op.drop_table("workspace_kill_switches")
