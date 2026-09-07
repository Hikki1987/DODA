"""Foundation schema: Identity, Customer, Workspace, Audit skeleton + RLS.

Implements the tenant-isolation invariant from ADR-005 / NFR-ISO-001:
every tenant-scoped table gets a row-level-security policy keyed on the
transaction-local `app.current_customer_id` GUC, in addition to (never
instead of) `customer_id` filtering in repository code. `current_setting`
is read in non-strict mode so an unset GUC evaluates to NULL and the
policy denies all rows — fail-closed per section 10.1.

Revision ID: 0001
Revises:
Create Date: 2026-09-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_SCOPED_TABLES = (
    "customer_memberships",
    "workspace_workspaces",
    "workspace_memberships",
    "audit_events",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "identity_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("oidc_subject_hash", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.UniqueConstraint("oidc_subject_hash"),
    )

    op.create_table(
        "customer_customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
    )

    op.create_table(
        "customer_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customer_customers.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
    )
    op.create_index("ix_customer_memberships_customer_id", "customer_memberships", ["customer_id"])
    op.create_index("ix_customer_memberships_user_id", "customer_memberships", ["user_id"])

    op.create_table(
        "workspace_workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workspace_workspaces_customer_id", "workspace_workspaces", ["customer_id"])

    op.create_table(
        "workspace_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspace_workspaces.id"), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
    )
    op.create_index("ix_workspace_memberships_customer_id", "workspace_memberships", ["customer_id"])
    op.create_index("ix_workspace_memberships_workspace_id", "workspace_memberships", ["workspace_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", sa.String(256), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("safe_metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("prev_hash", sa.String(64), nullable=True),
        sa.Column("hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_audit_events_customer_id", "audit_events", ["customer_id"])
    op.create_index("ix_audit_events_trace_id", "audit_events", ["trace_id"])

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

    # FR-AUD-001/004: audit is append-only. A trigger enforces this at the
    # database level regardless of which application role is connected.
    op.execute(
        """
        CREATE FUNCTION audit_events_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only: % not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_immutable()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_update_delete ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_immutable")

    for table in TENANT_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_table("audit_events")
    op.drop_table("workspace_memberships")
    op.drop_table("workspace_workspaces")
    op.drop_table("customer_memberships")
    op.drop_table("customer_customers")
    op.drop_table("identity_users")
