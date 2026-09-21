"""FR-TASK-005: reminder requests attached to a task ("aniq vaqt va
trigger foydalanuvchi tomonidan tasdiqlanadi"). Unlike task_decisions
(0020) this table IS mutated in place — a reminder moves through
PENDING_CONFIRMATION -> CONFIRMED -> FIRED (or -> CANCELLED at any point
before FIRED) — so it gets the same RLS treatment as task_tasks itself
(0002), not the append-only trigger pattern.

Also widens the two existing notification_type CHECK constraints
(0008/0009) to add REMINDER_DUE, a fifth, additive notification type
(doda.domain.notification.models.NotificationType) — never rewriting
those two migrations' own history, per the "migratsiya tarixini buzma"
rule.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "task_reminders"

REMINDER_STATUSES = ("PENDING_CONFIRMATION", "CONFIRMED", "CANCELLED", "FIRED")

OLD_NOTIFICATION_TYPES = ("PENDING_APPROVAL", "FAILED_ACTION", "COMPLETED_TASK", "SECURITY_ALERT")
NEW_NOTIFICATION_TYPES = (*OLD_NOTIFICATION_TYPES, "REMINDER_DUE")


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("task_tasks.id"), nullable=False),
        sa.Column("actor_id", sa.String(256), nullable=False),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"status IN {REMINDER_STATUSES}", name="ck_task_reminders_status"),
    )
    op.create_index(f"ix_{TABLE}_customer_id", TABLE, ["customer_id"])
    op.create_index(f"ix_{TABLE}_workspace_id", TABLE, ["workspace_id"])
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

    op.drop_constraint("ck_notifications_type", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_type", "notifications", f"notification_type IN {NEW_NOTIFICATION_TYPES}")
    op.drop_constraint("ck_notification_preferences_type", "notification_preferences", type_="check")
    op.create_check_constraint(
        "ck_notification_preferences_type",
        "notification_preferences",
        f"notification_type IN {NEW_NOTIFICATION_TYPES}",
    )


def downgrade() -> None:
    op.drop_constraint("ck_notification_preferences_type", "notification_preferences", type_="check")
    op.create_check_constraint(
        "ck_notification_preferences_type",
        "notification_preferences",
        f"notification_type IN {OLD_NOTIFICATION_TYPES}",
    )
    op.drop_constraint("ck_notifications_type", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_type", "notifications", f"notification_type IN {OLD_NOTIFICATION_TYPES}")

    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_table(TABLE)
