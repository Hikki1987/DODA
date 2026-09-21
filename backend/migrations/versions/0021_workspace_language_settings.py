"""FR-WKS-007's "til" facet: a workspace-level default language, versioned
(append-only, same trigger pattern as task_decisions/0020) and paired with
an audit event on every change (written by the application layer, not by
this migration).

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "workspace_language_settings"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspace_workspaces.id"), nullable=False
        ),
        sa.Column("actor_id", sa.String(256), nullable=False),
        sa.Column("language", sa.String(2), nullable=True),
    )
    op.create_index(f"ix_{TABLE}_customer_id", TABLE, ["customer_id"])
    op.create_index(f"ix_{TABLE}_workspace_id", TABLE, ["workspace_id"])

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {TABLE}
        USING (customer_id = current_setting('app.current_customer_id', true)::uuid)
        WITH CHECK (customer_id = current_setting('app.current_customer_id', true)::uuid)
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION workspace_language_settings_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '{TABLE} is append-only: % not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER workspace_language_settings_no_update_delete
        BEFORE UPDATE OR DELETE ON {TABLE}
        FOR EACH ROW EXECUTE FUNCTION workspace_language_settings_immutable()
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS workspace_language_settings_no_update_delete ON {TABLE}")
    op.execute("DROP FUNCTION IF EXISTS workspace_language_settings_immutable")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_table(TABLE)
