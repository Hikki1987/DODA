"""Scope Action.idempotency_key uniqueness by workspace, not just customer
(FR-ACT-004) — security fix. The old (customer_id, idempotency_key)
constraint meant two different workspaces under the same customer
choosing the same caller-supplied key collided onto the same Action row:
propose_action's idempotent-replay path (on the resulting IntegrityError)
looked the row up by (customer_id, idempotency_key) alone and returned it
— including its payload and, if AWAITING_APPROVAL, its pending approval's
one-time nonce — to a caller with no membership in the other workspace.
See doda.application.action_service.propose_action and
doda.domain.action.models.Action for the matching code-level fix.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_action_customer_idempotency_key", "action_actions", type_="unique")
    op.create_unique_constraint(
        "uq_action_workspace_idempotency_key",
        "action_actions",
        ["customer_id", "workspace_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_action_workspace_idempotency_key", "action_actions", type_="unique")
    op.create_unique_constraint(
        "uq_action_customer_idempotency_key", "action_actions", ["customer_id", "idempotency_key"]
    )
