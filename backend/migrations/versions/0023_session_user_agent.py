"""FR-AUTH-007: "Yangi qurilmadan login... security notification hosil
qiladi" — detecting a new device needs a device signal captured on the
session itself. Adds a nullable `user_agent` column to identity_sessions;
NULL means "unknown device" (the dev/test session-creation seam, and any
row created before this migration), which the detection logic in
session_service.py treats as "no evidence either way", never as
anomalous. identity_sessions has no customer_id column (Identity is the
one domain above the tenant boundary — a User can belong to many
customers), so this table is outside RLS's scope entirely; nothing here
changes that.

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("identity_sessions", sa.Column("user_agent", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("identity_sessions", "user_agent")
