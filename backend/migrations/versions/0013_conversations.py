"""FR-CONV scaffolding: Conversation + Message tables, same RLS treatment
as every other tenant-scoped table (ADR-005).

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_SCOPED_TABLES = ("conversation_conversations", "conversation_messages")
MESSAGE_ROLES = ("USER", "ASSISTANT")


def upgrade() -> None:
    op.create_table(
        "conversation_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", sa.String(256), nullable=False),
        sa.Column("title", sa.String(256), nullable=True),
    )
    op.create_index("ix_conversation_conversations_customer_id", "conversation_conversations", ["customer_id"])
    op.create_index("ix_conversation_conversations_workspace_id", "conversation_conversations", ["workspace_id"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversation_conversations.id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.CheckConstraint(f"role IN {MESSAGE_ROLES}", name="ck_conversation_messages_role"),
    )
    op.create_index("ix_conversation_messages_customer_id", "conversation_messages", ["customer_id"])
    op.create_index("ix_conversation_messages_conversation_id", "conversation_messages", ["conversation_id"])

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

    op.drop_table("conversation_messages")
    op.drop_table("conversation_conversations")
