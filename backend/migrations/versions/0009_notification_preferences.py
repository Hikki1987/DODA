"""Notification preferences table — FR-NTF-004. Absence of a row means
"enabled" (see doda.domain.notification.models.NotificationPreference);
SECURITY_ALERT is never allowed to be disabled — enforced in the
application layer (notification_service), not by a DB constraint, since
"only this one enum value is exempt" isn't expressible as a CHECK without
duplicating the enum's own values.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOTIFICATION_TYPES = ("PENDING_APPROVAL", "FAILED_ACTION", "COMPLETED_TASK", "SECURITY_ALERT")


def upgrade() -> None:
    op.create_table(
        "notification_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_id", sa.String(256), nullable=False),
        sa.Column("notification_type", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.CheckConstraint(
            f"notification_type IN {NOTIFICATION_TYPES}", name="ck_notification_preferences_type"
        ),
        sa.UniqueConstraint(
            "customer_id", "recipient_id", "notification_type", name="uq_notification_preferences_scope"
        ),
    )
    op.create_index("ix_notification_preferences_customer_id", "notification_preferences", ["customer_id"])
    op.create_index("ix_notification_preferences_recipient_id", "notification_preferences", ["recipient_id"])

    op.execute("ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notification_preferences FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON notification_preferences
        USING (customer_id = current_setting('app.current_customer_id', true)::uuid)
        WITH CHECK (customer_id = current_setting('app.current_customer_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON notification_preferences")
    op.drop_table("notification_preferences")
