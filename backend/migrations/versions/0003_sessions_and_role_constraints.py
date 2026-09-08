"""S2 prerequisite: Session (FR-AUTH-003/005/006) + role CHECK constraints.

Building an HTTP API on top of S1's action_service without a real
authorization chain would violate the master instruction ("Identity ->
Customer -> Workspace -> RBAC -> Policy -> Step-Up -> Authorization
zanjirini chetlab o'tma") and NFR-ISO-001. This migration adds the minimum
real (non-mocked) piece needed: session validity, and role values
constrained at the database level, not just trusted from application code.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CUSTOMER_ROLES = ("platform_owner", "customer_owner", "member", "auditor")
WORKSPACE_ROLES = ("workspace_admin", "member")
AUTH_STRENGTHS = ("AAL1", "AAL2")


def upgrade() -> None:
    op.create_table(
        "identity_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("identity_users.id"), nullable=False),
        sa.Column("auth_strength", sa.String(8), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"auth_strength IN {AUTH_STRENGTHS}", name="ck_identity_sessions_auth_strength"),
    )
    op.create_index("ix_identity_sessions_user_id", "identity_sessions", ["user_id"])

    op.create_check_constraint(
        "ck_customer_memberships_role", "customer_memberships", f"role IN {CUSTOMER_ROLES}"
    )
    op.create_check_constraint(
        "ck_workspace_memberships_role", "workspace_memberships", f"role IN {WORKSPACE_ROLES}"
    )


def downgrade() -> None:
    op.drop_constraint("ck_workspace_memberships_role", "workspace_memberships", type_="check")
    op.drop_constraint("ck_customer_memberships_role", "customer_memberships", type_="check")
    op.drop_table("identity_sessions")
