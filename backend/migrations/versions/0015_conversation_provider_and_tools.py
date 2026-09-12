"""Multi-provider support for FR-CONV — ADR-009. Additive to 0013 (which
is already shared/pushed history, so it is not edited in place):

- conversation_conversations: pinned_provider/pinned_model (explicit
  in-conversation provider switch, doda.application.ai_preference_service).
- conversation_messages: provider/model/finish_reason attribution per
  ASSISTANT message, and tool_call_id/tool_name/tool_arguments_json for
  representing a tool-call turn + its result turn — plus a new 'TOOL'
  value added to the role CHECK constraint.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_MESSAGE_ROLES = ("USER", "ASSISTANT")
NEW_MESSAGE_ROLES = ("USER", "ASSISTANT", "TOOL")


def upgrade() -> None:
    op.add_column(
        "conversation_conversations", sa.Column("pinned_provider", sa.String(16), nullable=True)
    )
    op.add_column("conversation_conversations", sa.Column("pinned_model", sa.String(64), nullable=True))

    op.add_column("conversation_messages", sa.Column("tool_call_id", sa.String(128), nullable=True))
    op.add_column("conversation_messages", sa.Column("tool_name", sa.String(128), nullable=True))
    op.add_column("conversation_messages", sa.Column("tool_arguments_json", sa.Text, nullable=True))
    op.add_column("conversation_messages", sa.Column("provider", sa.String(16), nullable=True))
    op.add_column("conversation_messages", sa.Column("model", sa.String(64), nullable=True))
    op.add_column("conversation_messages", sa.Column("finish_reason", sa.String(16), nullable=True))

    op.drop_constraint("ck_conversation_messages_role", "conversation_messages", type_="check")
    op.create_check_constraint(
        "ck_conversation_messages_role", "conversation_messages", f"role IN {NEW_MESSAGE_ROLES}"
    )


def downgrade() -> None:
    op.drop_constraint("ck_conversation_messages_role", "conversation_messages", type_="check")
    op.create_check_constraint(
        "ck_conversation_messages_role", "conversation_messages", f"role IN {OLD_MESSAGE_ROLES}"
    )

    op.drop_column("conversation_messages", "finish_reason")
    op.drop_column("conversation_messages", "model")
    op.drop_column("conversation_messages", "provider")
    op.drop_column("conversation_messages", "tool_arguments_json")
    op.drop_column("conversation_messages", "tool_name")
    op.drop_column("conversation_messages", "tool_call_id")

    op.drop_column("conversation_conversations", "pinned_model")
    op.drop_column("conversation_conversations", "pinned_provider")
