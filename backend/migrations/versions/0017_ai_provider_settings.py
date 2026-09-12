"""Per-provider administrative settings — ADR-009's provider settings
gap. `ai_customer_provider_settings` is one row per (customer, provider)
a CustomerOwner has explicitly disabled (row absence = enabled, same
convention as notification_preferences). `ai_provider_verifications` is
NOT customer-scoped — the credential itself is a server-wide
`doda.config.Settings` value, not per-customer, so whether it works is a
server-wide fact (see doda.domain.ai_provider_settings.models for why).

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROVIDERS = ("OPENAI", "GEMINI", "CLAUDE")


def upgrade() -> None:
    op.create_table(
        "ai_customer_provider_settings",
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(16), primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.CheckConstraint(f"provider IN {PROVIDERS}", name="ck_ai_customer_provider_settings_provider"),
    )
    op.execute("ALTER TABLE ai_customer_provider_settings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_customer_provider_settings FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON ai_customer_provider_settings
        USING (customer_id = current_setting('app.current_customer_id', true)::uuid)
        WITH CHECK (customer_id = current_setting('app.current_customer_id', true)::uuid)
        """
    )

    # Not tenant-scoped — no customer_id column, no RLS (see module
    # docstring and the model's own docstring for why this is correct,
    # not an oversight).
    op.create_table(
        "ai_provider_verifications",
        sa.Column("provider", sa.String(16), primary_key=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_verified_ok", sa.Boolean, nullable=False),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("last_error_type", sa.String(64), nullable=True),
        sa.CheckConstraint(f"provider IN {PROVIDERS}", name="ck_ai_provider_verifications_provider"),
    )


def downgrade() -> None:
    op.drop_table("ai_provider_verifications")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_customer_provider_settings")
    op.drop_table("ai_customer_provider_settings")
