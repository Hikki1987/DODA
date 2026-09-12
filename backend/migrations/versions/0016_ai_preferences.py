"""Provider/model selection persistence — ADR-009. One row per (customer,
user) for a personal default, one row per workspace for its default.
Both RLS-protected like every other tenant-scoped table (ADR-005).

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROVIDERS = ("OPENAI", "GEMINI", "CLAUDE")
TENANT_SCOPED_TABLES = ("user_ai_preferences", "workspace_ai_preferences")


def upgrade() -> None:
    op.create_table(
        "user_ai_preferences",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("model", sa.String(64), nullable=True),
        sa.CheckConstraint(f"provider IN {PROVIDERS}", name="ck_user_ai_preferences_provider"),
    )

    op.create_table(
        "workspace_ai_preferences",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("model", sa.String(64), nullable=True),
        sa.CheckConstraint(f"provider IN {PROVIDERS}", name="ck_workspace_ai_preferences_provider"),
    )
    op.create_index("ix_workspace_ai_preferences_customer_id", "workspace_ai_preferences", ["customer_id"])

    for table in TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (customer_id = current_setting('app.current_customer_id', true)::uuid)
            WITH CHECK (customer_id = current_setting('app.current_customer_id', true)::uuid)
            """
        )


def downgrade() -> None:
    for table in TENANT_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_table("workspace_ai_preferences")
    op.drop_table("user_ai_preferences")
