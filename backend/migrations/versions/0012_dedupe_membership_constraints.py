"""Unique constraints preventing duplicate memberships (FR-WKS-003/005) —
data-integrity fix. Neither customer_memberships(customer_id, user_id)
nor workspace_memberships(customer_membership_id, workspace_id) had a
uniqueness guarantee: nothing stopped two independent membership rows
for the same person in the same customer/workspace — reachable via a
double-clicked "Qo'shish" invite/add button (no in-flight guard on the
frontend) or two admins inviting the same person at once. A duplicate
row meant the same person listed twice in list_customer_members /
list_workspace_members, each row independently editable and removable.
See doda.application.customer_service.invite_customer_member and
doda.application.workspace_service.add_workspace_member for the matching
code-level fix (insert inside a SAVEPOINT, catch the resulting
IntegrityError and raise a clear DuplicateMembership*Error instead of a
raw 500) — same established pattern as 0010's Action.idempotency_key fix.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_customer_membership_customer_user", "customer_memberships", ["customer_id", "user_id"]
    )
    op.create_unique_constraint(
        "uq_workspace_membership_customer_membership_workspace",
        "workspace_memberships",
        ["customer_membership_id", "workspace_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_workspace_membership_customer_membership_workspace", "workspace_memberships", type_="unique"
    )
    op.drop_constraint("uq_customer_membership_customer_user", "customer_memberships", type_="unique")
