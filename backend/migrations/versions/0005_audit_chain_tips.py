"""Resolve a known limitation: the audit hash chain (FR-AUD-004) was not
safe under concurrent writers for the same customer — two concurrent
transactions could read the same "latest event" and fork the chain. This
adds a per-customer serialization point locked with SELECT ... FOR UPDATE
in doda.application.audit_service before the previous approach (ORDER BY
created_at DESC LIMIT 1, no lock) is removed by this same change.

Backfilled from the current tip of each customer's existing chain so
history already written under the old approach keeps chaining correctly.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_chain_tips",
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tip_hash", sa.String(64), nullable=True),
    )
    op.execute("ALTER TABLE audit_chain_tips ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_chain_tips FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON audit_chain_tips
        USING (customer_id = current_setting('app.current_customer_id', true)::uuid)
        WITH CHECK (customer_id = current_setting('app.current_customer_id', true)::uuid)
        """
    )

    # Backfill: for each customer with existing audit_events, seed the tip
    # with their chain's current last hash (by created_at). Same FORCE RLS
    # bypass technique as 0004's backfill — the migration connection would
    # otherwise see zero rows across all customers.
    op.execute("ALTER TABLE audit_events NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_chain_tips NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        INSERT INTO audit_chain_tips (customer_id, tip_hash)
        SELECT DISTINCT ON (customer_id) customer_id, hash
        FROM audit_events
        ORDER BY customer_id, created_at DESC
        ON CONFLICT (customer_id) DO NOTHING
        """
    )
    op.execute("ALTER TABLE audit_chain_tips FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON audit_chain_tips")
    op.drop_table("audit_chain_tips")
