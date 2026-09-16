"""FR-TASK-003: decision records attached to a task (variant, tradeoff,
decision, reason). "Qaror versiyalanadi; oldingi versiya o'chirilmaydi" —
each call creates a NEW row (a new version); a DB trigger blocks
UPDATE/DELETE outright, the same append-only enforcement 0001 already
uses for audit_events, so the guarantee does not depend on which
application role is connected.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "task_decisions"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("task_tasks.id"), nullable=False),
        sa.Column("actor_id", sa.String(256), nullable=False),
        sa.Column("variant", sa.Text, nullable=False),
        sa.Column("tradeoff", sa.Text, nullable=False),
        sa.Column("decision", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
    )
    op.create_index(f"ix_{TABLE}_customer_id", TABLE, ["customer_id"])
    op.create_index(f"ix_{TABLE}_task_id", TABLE, ["task_id"])

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
        CREATE FUNCTION task_decisions_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '{TABLE} is append-only: % not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER task_decisions_no_update_delete
        BEFORE UPDATE OR DELETE ON {TABLE}
        FOR EACH ROW EXECUTE FUNCTION task_decisions_immutable()
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS task_decisions_no_update_delete ON {TABLE}")
    op.execute("DROP FUNCTION IF EXISTS task_decisions_immutable")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_table(TABLE)
