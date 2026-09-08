"""Notifications table — FR-NTF. In-app only (email/Telegram are future
adapters per FR-NTF-001). See doda.domain.notification.models for why
there is no free-text message column.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOTIFICATION_TYPES = ("PENDING_APPROVAL", "FAILED_ACTION", "COMPLETED_TASK", "SECURITY_ALERT")


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recipient_id", sa.String(256), nullable=False),
        sa.Column("notification_type", sa.String(32), nullable=False),
        sa.Column("reference_type", sa.String(64), nullable=False),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("safe_metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"notification_type IN {NOTIFICATION_TYPES}", name="ck_notifications_type"),
    )
    op.create_index("ix_notifications_customer_id", "notifications", ["customer_id"])
    op.create_index("ix_notifications_workspace_id", "notifications", ["workspace_id"])
    op.create_index("ix_notifications_recipient_id", "notifications", ["recipient_id"])

    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notifications FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON notifications
        USING (customer_id = current_setting('app.current_customer_id', true)::uuid)
        WITH CHECK (customer_id = current_setting('app.current_customer_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON notifications")
    op.drop_table("notifications")
