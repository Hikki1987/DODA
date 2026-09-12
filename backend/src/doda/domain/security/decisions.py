"""Authorization decision vocabulary — section 10, authoritative chain:
Authentication Session -> Customer Membership -> Workspace Membership ->
RBAC -> ABAC Policy -> Step-Up -> Decision. "Mos explicit permission
topilmasa natija DENY bo'ladi" (fail-closed, 10.1) — every authz function
in doda.application.authz_service must raise rather than default-allow.
"""

import enum


class Decision(enum.StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    STEP_UP_REQUIRED = "STEP_UP_REQUIRED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
