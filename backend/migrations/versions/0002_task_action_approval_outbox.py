"""S1: Task/Action/Approval domain + transactional outbox (17.2 sprint plan).

Task, Action and Approval carry customer_id and get the same RLS treatment
as 0001's tenant-scoped tables (ADR-005). outbox_messages deliberately does
not — see doda.domain.outbox.models for why.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_SCOPED_TABLES = ("task_tasks", "task_history", "action_actions", "action_approvals")

TASK_STATUSES = ("TODO", "IN_PROGRESS", "DONE", "CANCELLED")
RISK_LEVELS = ("R0", "R1", "R2", "R3", "R4", "R5")
ACTION_STATUSES = (
    "DRAFT", "VALIDATING", "AWAITING_APPROVAL", "READY", "RUNNING",
    "SUCCEEDED", "FAILED", "RETRYING", "COMPENSATING", "COMPENSATED",
    "DENIED", "REJECTED", "EXPIRED", "CANCELLED",
)
APPROVAL_STATUSES = ("PENDING", "APPROVED", "DENIED", "EXPIRED")


def upgrade() -> None:
    op.create_table(
        "task_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", sa.String(256), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("parent_task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("task_tasks.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"status IN {TASK_STATUSES}", name="ck_task_tasks_status"),
    )
    op.create_index("ix_task_tasks_customer_id", "task_tasks", ["customer_id"])
    op.create_index("ix_task_tasks_workspace_id", "task_tasks", ["workspace_id"])

    op.create_table(
        "task_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("task_tasks.id"), nullable=False),
        sa.Column("actor_id", sa.String(256), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.CheckConstraint(f"from_status IS NULL OR from_status IN {TASK_STATUSES}", name="ck_task_history_from_status"),
        sa.CheckConstraint(f"to_status IN {TASK_STATUSES}", name="ck_task_history_to_status"),
    )
    op.create_index("ix_task_history_customer_id", "task_history", ["customer_id"])
    op.create_index("ix_task_history_task_id", "task_history", ["task_id"])

    op.create_table(
        "action_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", sa.String(256), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("risk_level", sa.String(2), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.CheckConstraint(f"risk_level IN {RISK_LEVELS}", name="ck_action_actions_risk_level"),
        sa.CheckConstraint(f"status IN {ACTION_STATUSES}", name="ck_action_actions_status"),
        sa.UniqueConstraint("customer_id", "idempotency_key", name="uq_action_customer_idempotency_key"),
    )
    op.create_index("ix_action_actions_customer_id", "action_actions", ["customer_id"])
    op.create_index("ix_action_actions_workspace_id", "action_actions", ["workspace_id"])
    op.create_index("ix_action_actions_trace_id", "action_actions", ["trace_id"])

    op.create_table(
        "action_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("action_actions.id"), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("approver_id", sa.String(256), nullable=True),
        sa.Column("nonce", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"status IN {APPROVAL_STATUSES}", name="ck_action_approvals_status"),
    )
    op.create_index("ix_action_approvals_customer_id", "action_approvals", ["customer_id"])
    op.create_index("ix_action_approvals_action_id", "action_approvals", ["action_id"])

    op.create_table(
        "outbox_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_outbox_messages_customer_id", "outbox_messages", ["customer_id"])
    op.create_index("ix_outbox_messages_aggregate_id", "outbox_messages", ["aggregate_id"])
    op.create_index("ix_outbox_messages_published_at", "outbox_messages", ["published_at"])

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

    op.drop_table("outbox_messages")
    op.drop_table("action_approvals")
    op.drop_table("action_actions")
    op.drop_table("task_history")
    op.drop_table("task_tasks")
