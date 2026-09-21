"""FR-ADM-005: "AI byudjeti va limitlarni belgilash" — a per-customer
override of the deployment-wide default soft/hard AI budget caps
(Settings.ai_budget_soft_usd_per_customer_month/
ai_budget_hard_usd_per_customer_month). Same RLS shape as
ai_budget_ledgers (0014): customer_id as the primary key, FORCE ROW
LEVEL SECURITY, tenant_isolation policy.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "ai_budget_overrides"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("soft_cap_cents", sa.Integer(), nullable=False),
        sa.Column("hard_cap_cents", sa.Integer(), nullable=False),
    )

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {TABLE}
        USING (customer_id = current_setting('app.current_customer_id', true)::uuid)
        WITH CHECK (customer_id = current_setting('app.current_customer_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_table(TABLE)
