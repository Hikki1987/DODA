"""FR-TASK-006: links a task to an uploaded Knowledge document ("evidence
va fayl bilan bog'lash"). `document_id` is a bare UUID, not a foreign
key to `knowledge_documents` — that table belongs to a different domain
(Knowledge), and 6.2's isolation rule means Task holds only a reference,
never a hard coupling to its implementation. A plain, detachable link
(no append-only trigger, unlike task_decisions/0020) — its own
acceptance criterion only requires that a deleted document shows up as
a broken link on the task, not that the link record itself is
immutable.

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "task_attachments"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("task_tasks.id"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attached_by", sa.String(256), nullable=False),
    )
    op.create_index(f"ix_{TABLE}_customer_id", TABLE, ["customer_id"])
    op.create_index(f"ix_{TABLE}_workspace_id", TABLE, ["workspace_id"])
    op.create_index(f"ix_{TABLE}_task_id", TABLE, ["task_id"])
    op.create_index(f"ix_{TABLE}_document_id", TABLE, ["document_id"])

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {TABLE}
        USING (customer_id = current_setting('app.current_customer_id', true)::uuid)
        WITH CHECK (customer_id = current_setting('app.current_customer_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_table(TABLE)
