"""FR-CONV-001: "foydalanuvchi tanlovi avtomatik aniqlashdan ustun" — an
explicit per-conversation language override, same shape and same
semantics as 0015's pinned_provider/pinned_model (set only via an
explicit switch, never auto-propagated from/to the user's or workspace's
anything — there is no user/workspace-level language default here, only
per-conversation, since nothing in this TRD asks for one). NULL means
"no override — use whatever doda.ai.language.detect_language says about
the CURRENT message".

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversation_conversations", sa.Column("pinned_language", sa.String(2), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("conversation_conversations", "pinned_language")
