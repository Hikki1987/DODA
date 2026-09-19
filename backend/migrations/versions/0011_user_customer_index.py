"""User-customer bootstrap index — same pattern as 0004's
workspace_tenant_index, one level up. See
doda.domain.customer.models.UserCustomerIndex for why this table exists
and deliberately carries no RLS policy.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_customer_index",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), primary_key=True),
    )
    op.create_index("ix_user_customer_index_customer_id", "user_customer_index", ["customer_id"])

    # Backfill for any membership created before this table existed.
    # customer_memberships has FORCE ROW LEVEL SECURITY (0001), which binds
    # even the table owner — toggle FORCE off only for this owner-run
    # backfill, then restore it (same pattern as 0004's backfill).
    op.execute("ALTER TABLE customer_memberships NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "INSERT INTO user_customer_index (user_id, customer_id) "
        "SELECT DISTINCT user_id, customer_id FROM customer_memberships "
        "ON CONFLICT (user_id, customer_id) DO NOTHING"
    )
    op.execute("ALTER TABLE customer_memberships FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("user_customer_index")
