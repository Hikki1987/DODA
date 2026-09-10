"""Seed a demo Customer/Workspace/User/Action for the frontend E2E suite.

Not a pytest fixture: the E2E suite drives a real, separately-running
backend process over HTTP (frontend/e2e/*.spec.ts), so seeding has to
happen out-of-process, before that server (and the frontend) start. This
script is that seam — it writes directly to the DB the running backend
will read from, then prints the IDs the E2E tests need as plain
KEY=VALUE lines so a CI step can capture them into env vars.

Deliberately bypasses the public API for identity/session creation the
same way tests/integration/conftest.py's seed_workspace_member does:
FR-AUTH-001's real OIDC login is still S3 future work (see CLAUDE.md), so
there is no HTTP-reachable way to mint a session yet. This is that same
"dev/test seam", just as a standalone script instead of a pytest fixture.
"""

import argparse
import asyncio
import uuid

from doda.application.action_service import propose_action, submit_action_for_execution
from doda.application.session_service import create_session
from doda.application.workspace_service import create_workspace
from doda.db import tenant_scoped_session
from doda.domain.action.models import RiskLevel
from doda.domain.customer.models import Customer, CustomerMembership, UserCustomerIndex
from doda.domain.identity.models import AuthStrength, User
from doda.domain.workspace.models import WorkspaceMembership


async def main(prefix: str) -> None:
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as db:
        owner = User(oidc_subject_hash=str(uuid.uuid4()), display_name="Demo User")
        db.add(owner)
        await db.flush()

        db.add(Customer(id=customer_id, name="Demo Customer"))
        await db.flush()

        owner_membership = CustomerMembership(
            customer_id=customer_id, user_id=owner.id, role="customer_owner"
        )
        db.add(owner_membership)
        db.add(UserCustomerIndex(user_id=owner.id, customer_id=customer_id))
        await db.flush()

        workspace = await create_workspace(db, customer_id=customer_id, name="Demo Workspace")
        db.add(
            WorkspaceMembership(
                customer_id=customer_id,
                customer_membership_id=owner_membership.id,
                workspace_id=workspace.id,
                role="workspace_admin",
            )
        )
        await db.flush()

        session_record = await create_session(db, user_id=owner.id, auth_strength=AuthStrength.AAL2)

        action, _created = await propose_action(
            db,
            customer_id=customer_id,
            workspace_id=workspace.id,
            trace_id=uuid.uuid4(),
            actor_id=f"user:{owner.id}",
            tool_name="send_email",
            risk_level=RiskLevel.R3,
            payload={"to": "demo@example.com"},
            idempotency_key=str(uuid.uuid4()),
            task_id=None,
        )
        await submit_action_for_execution(db, action, actor_id=f"user:{owner.id}")

        # A second, unaffiliated Identity User — the customer-page E2E spec
        # invites this user as a real member (POST /v1/customers/{id}/members
        # 404s on an unknown user_id, so it must already exist).
        invitee = User(oidc_subject_hash=str(uuid.uuid4()), display_name="Second User")
        db.add(invitee)
        await db.flush()

        # A real read-only auditor on the same customer: a CustomerRole.AUDITOR
        # holds no workspace role by design (10.2), so this is the one seeded
        # identity whose entire access lives on the customer page — what
        # e2e/auditor.spec.ts checks. Deliberately NOT given a
        # WorkspaceMembership: add_workspace_member refuses that pairing now.
        auditor = User(oidc_subject_hash=str(uuid.uuid4()), display_name="Audit Reviewer")
        db.add(auditor)
        await db.flush()
        db.add(CustomerMembership(customer_id=customer_id, user_id=auditor.id, role="auditor"))
        db.add(UserCustomerIndex(user_id=auditor.id, customer_id=customer_id))
        await db.flush()
        auditor_session = await create_session(db, user_id=auditor.id, auth_strength=AuthStrength.AAL1)

    print(f"{prefix}SESSION_ID={session_record.id}")
    print(f"{prefix}WORKSPACE_ID={workspace.id}")
    print(f"{prefix}CUSTOMER_ID={customer_id}")
    print(f"{prefix}SECOND_USER_ID={invitee.id}")
    print(f"{prefix}AUDITOR_SESSION_ID={auditor_session.id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prefix",
        default="E2E_",
        help="Env var name prefix for the printed IDs (default: E2E_). Use a "
        "distinct prefix per invocation so independent spec files don't "
        "share mutable seeded state (e.g. one test's kill-switch broadcast "
        "leaking a notification into another test's assertions).",
    )
    args = parser.parse_args()
    asyncio.run(main(args.prefix))
