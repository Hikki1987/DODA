"""AI usage/cost accounting — NFR-COST-001, ADR-008. `ai_usage_events` is
one row per gateway call (RESERVED -> RECONCILED/REFUNDED);
`ai_budget_ledgers` is one row per (customer, calendar month), locked with
SELECT ... FOR UPDATE before every change (see
doda.application.ai_budget_service) — the same proven concurrency-safe
pattern as audit_chain_tips/workspace_kill_switches/etc.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

USAGE_MODES = ("FAST", "STANDARD", "DEEP")
USAGE_PROVIDERS = ("OPENAI", "GEMINI", "CLAUDE")
USAGE_EVENT_STATUSES = ("RESERVED", "RECONCILED", "REFUNDED")

TENANT_SCOPED_TABLES = ("ai_usage_events", "ai_budget_ledgers")


def upgrade() -> None:
    op.create_table(
        "ai_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", sa.String(256), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cached_input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("estimated_cost_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("actual_cost_cents", sa.Integer, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="RESERVED"),
        sa.CheckConstraint(f"provider IN {USAGE_PROVIDERS}", name="ck_ai_usage_events_provider"),
        sa.CheckConstraint(f"mode IN {USAGE_MODES}", name="ck_ai_usage_events_mode"),
        sa.CheckConstraint(f"status IN {USAGE_EVENT_STATUSES}", name="ck_ai_usage_events_status"),
    )
    op.create_index("ix_ai_usage_events_customer_id", "ai_usage_events", ["customer_id"])
    op.create_index("ix_ai_usage_events_workspace_id", "ai_usage_events", ["workspace_id"])
    op.create_index("ix_ai_usage_events_trace_id", "ai_usage_events", ["trace_id"])

    op.create_table(
        "ai_budget_ledgers",
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("year_month", sa.String(7), primary_key=True),
        sa.Column("reserved_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("actual_cents", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_ai_budget_ledgers_customer_id", "ai_budget_ledgers", ["customer_id"])

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

    op.drop_table("ai_budget_ledgers")
    op.drop_table("ai_usage_events")
