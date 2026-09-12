"""Opt-in, default-OFF automatic fallback toggle — one row per customer,
row absence means DISABLED (the opposite convention from
ai_customer_provider_settings, deliberately: silent automatic
substitution must never be the unstated default). RLS-protected like
every other tenant-scoped table (ADR-005).

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_customer_fallback_settings",
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="false"),
    )
    op.execute("ALTER TABLE ai_customer_fallback_settings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_customer_fallback_settings FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON ai_customer_fallback_settings
        USING (customer_id = current_setting('app.current_customer_id', true)::uuid)
        WITH CHECK (customer_id = current_setting('app.current_customer_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_customer_fallback_settings")
    op.drop_table("ai_customer_fallback_settings")
