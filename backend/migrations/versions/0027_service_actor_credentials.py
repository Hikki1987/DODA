"""FR-AUTH-009: Service Actor uchun alohida machine credential oqimi.

Adds `identity_sessions.actor_kind` (human | service, default human — a
non-null backfill for every existing row, since a Session with no opinion
either way must be treated as human, never as the more-restricted kind)
and `service_actor_credentials`, a machine-credential table that is
deliberately NOT row-level-secured — see
doda.domain.identity.models.ServiceActorCredential's docstring: verifying
a presented secret has to happen before any customer_id is known, the
same bootstrap problem workspace_tenant_index/user_customer_index solve
one level up. This is `tests/integration/test_rls_coverage.py`'s fourth
documented exemption.

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "service_actor_credentials"


def upgrade() -> None:
    op.add_column(
        "identity_sessions",
        sa.Column("actor_kind", sa.String(8), nullable=False, server_default="human"),
    )

    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("identity_users.id"), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("secret_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("identity_users.id"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(f"ix_{TABLE}_customer_id", TABLE, ["customer_id"])
    op.create_index(f"ix_{TABLE}_secret_hash", TABLE, ["secret_hash"], unique=True)
    # Deliberately no ENABLE/FORCE ROW LEVEL SECURITY here — see this
    # migration's own docstring and KNOWN_RLS_EXEMPT_TABLES.


def downgrade() -> None:
    op.drop_table(TABLE)
    op.drop_column("identity_sessions", "actor_kind")
