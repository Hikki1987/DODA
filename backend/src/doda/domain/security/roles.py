"""Security domain — role vocabulary and the permission matrix from section
10.2. This is the "Security" module named explicitly in 6.1's layer table,
kept separate from Identity/Customer/Workspace because it encodes policy
(who may do what), not an aggregate.

CustomerRole.CUSTOMER_OWNER resolves as WorkspaceRole.WORKSPACE_ADMIN for
any workspace under their customer — see
authz_service.get_workspace_context — because 10.2 grants CustomerOwner
the same or greater authority than WorkspaceAdmin on every row that has a
WorkspaceAdmin column (role assignment, R3 approval, workspace lifecycle).
This is resolved once, at context-construction time, rather than
re-checked in every authorize_* function, so a CustomerOwner need not hold
any WorkspaceMembership row at all to have this authority.

Also excludes Service Actor and Platform Owner: neither has an HTTP-facing
use case yet (Service Actor never approves per 2.2's invariant; Platform
Owner's R5 dual-control flow is S4/S6 scope).
"""

import enum


class CustomerRole(str, enum.Enum):
    CUSTOMER_OWNER = "customer_owner"
    MEMBER = "member"
    AUDITOR = "auditor"


class WorkspaceRole(str, enum.Enum):
    WORKSPACE_ADMIN = "workspace_admin"
    MEMBER = "member"


# 10.2 "R3 action bajarish" row: Member/WorkspaceAdmin/CustomerOwner =
# "Approval bilan"; Auditor = "Yo'q". CustomerRole.AUDITOR has no
# WorkspaceRole counterpart by design (auditors are read-only, 2.2) so it
# never appears here.
ROLES_THAT_MAY_PROPOSE_ACTIONS = frozenset({WorkspaceRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN})

# 9.1's R3 approver is "Foydalanuvchining o'zi" (the proposer, self-approval
# under fresh MFA) — enforced separately as an actor-identity check, not a
# role check, in doda.application.authz_service.authorize_consume_approval.
# A WorkspaceRole.WORKSPACE_ADMIN may additionally approve someone else's
# R3 action (a supervisor override) — and so may a CustomerRole.CUSTOMER_OWNER,
# since they resolve as WORKSPACE_ADMIN here (see this module's docstring);
# Auditor never can.
ROLES_THAT_MAY_APPROVE_ANOTHER_ACTORS_ACTION = frozenset({WorkspaceRole.WORKSPACE_ADMIN})
