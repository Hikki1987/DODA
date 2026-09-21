"""Trace completeness job (NFR-OBS-001: "100% action/approval trace
korrelyatsiyasi" — Tekshiruv: "Trace completeness job", named verbatim
in the TRD's own row for this NFR).

The WRITE half of trace correlation is tested at
tests/integration/test_actions_api.py::test_action_trace_id_matches_
the_http_requests_own_trace_id (an Action's own trace_id matches the
HTTP request that created it) and the READ half at
tests/integration/test_audit_api.py (GET .../audit?trace_id= actually
filters). Neither checks the underlying INVARIANT across real,
accumulated data: that every audit event correlated with a given Action
(via safe_metadata["action_id"]) carries THAT Action's own trace_id, not
some other value. Nothing in the schema enforces this — trace_id is a
plain, NOT NULL column on both `actions` and `audit_events`
independently, not a foreign-key-like constraint tying one to the
other — it is purely an application-level discipline (every
apply_transition/propose_action call passes the action's own trace_id
to record_audit_event). A future code path that forgot this (e.g. a new
connector minting its own uuid4() instead of reusing action.trace_id,
the exact bug FR-ACT/api/actions.py's own history already had once
before it was fixed — see CLAUDE.md's NFR-OBS-001 entry) would silently
degrade "100%" trace correlation without any test here ever noticing,
since existing tests only exercise one action/one request at a time.

Same turkum as verify_audit_chain_job.py/find_stuck_running_actions.py:
an independent script, not a pytest test (per this codebase's own
convention for these — verified manually, see below), discovering
customers via `customer_service.list_all_customer_ids` (the RLS-exempt
UserCustomerIndex bootstrap table), and reporting violations to stderr
with a non-zero exit code — there is no paging/alerting infrastructure
yet, so the exit code + stderr output IS the alert, meant for a
cron/systemd wrapper.
"""

import asyncio
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doda.application.customer_service import list_all_customer_ids
from doda.db import tenant_scoped_session
from doda.domain.action.models import Action
from doda.domain.audit.models import AuditEvent


async def check_customer_trace_completeness(session: AsyncSession, *, customer_id: uuid.UUID) -> list[str]:
    """Returns a human-readable violation string for every audit event
    whose safe_metadata references an action_id but carries a different
    trace_id than that action's own — empty list means fully correlated.
    """
    actions = (await session.execute(select(Action))).scalars().all()
    if not actions:
        return []
    action_trace_by_id = {str(action.id): action.trace_id for action in actions}

    events = (await session.execute(select(AuditEvent))).scalars().all()
    violations = []
    for event in events:
        action_id = event.safe_metadata.get("action_id")
        if action_id is None or action_id not in action_trace_by_id:
            continue
        expected_trace_id = action_trace_by_id[action_id]
        if event.trace_id != expected_trace_id:
            violations.append(
                f"customer={customer_id} action={action_id} action.trace_id={expected_trace_id} "
                f"but audit event {event.id} ({event.event_type}) carries trace_id={event.trace_id}"
            )
    return violations


async def main() -> int:
    customer_ids = await list_all_customer_ids()

    exit_code = 0
    checked_customers = 0
    for customer_id in customer_ids:
        async with tenant_scoped_session(customer_id) as db:
            violations = await check_customer_trace_completeness(db, customer_id=customer_id)
        checked_customers += 1
        if violations:
            exit_code = 1
            for violation in violations:
                print(violation, file=sys.stderr)

    if exit_code == 0:
        print(f"trace completeness OK — {checked_customers} customers checked, 0 mismatches")
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
