"""Stuck-COMPENSATING Action detector.

FR-ACT-009 (`application/action_service.complete_compensation`) is
deliberately human-attested: there is no automated reversal to run for
the one real connector (Telegram's Bot API has no message-delete/undo
call this codebase's client uses), so an Action stays in COMPENSATING
until a WorkspaceAdmin calls `POST .../compensate/complete` themself.
That is the right design (see complete_compensation's own docstring),
but it has the same observability gap `find_stuck_running_actions.py`
already documented for RUNNING: nothing ever revisits a COMPENSATING
Action on its own, so if the admin who requested the reversal forgets
about it (or was never told to expect a manual step), the Action sits
there invisibly forever — no relay worker, no timer, no notification
loop touches it.

This script does not attempt to resolve a stuck compensation — deciding
whether a given reversal actually happened is exactly the human
judgment call FR-ACT-009 pushed onto a WorkspaceAdmin, not something a
monitoring script should guess at. It only makes the gap observable, the
same "alert is this process's exit status" approach as
verify_audit_chain_job.py and find_stuck_running_actions.py, so an
operator has something to act on instead of a silently stuck action.

Discovers every customer via `customer_service.list_all_customer_ids`,
same pattern as the other ops scripts in this directory. For each
customer, an Action still in COMPENSATING is "stuck" once its own
`action.compensating.v1` audit event (written by `apply_transition` at
the moment `request_cancellation` made that transition) is older than
`threshold` — deliberately much longer than RUNNING's 15-minute default,
since completing a compensation is a human's out-of-band task, not a
worker's, and needs realistic time to notice and act.
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from doda.application.customer_service import list_all_customer_ids
from doda.db import tenant_scoped_session
from doda.domain.action.models import Action, ActionStatus
from doda.domain.audit.models import AuditEvent

DEFAULT_STUCK_THRESHOLD = timedelta(hours=1)


async def main(threshold: timedelta = DEFAULT_STUCK_THRESHOLD) -> int:
    customer_ids = await list_all_customer_ids()

    cutoff = datetime.now(UTC) - threshold
    exit_code = 0
    for customer_id in customer_ids:
        async with tenant_scoped_session(customer_id) as db:
            compensating_actions = (
                await db.scalars(select(Action).where(Action.status == ActionStatus.COMPENSATING))
            ).all()
            if not compensating_actions:
                continue

            # One query per customer rather than per action — same
            # rationale as find_stuck_running_actions.py: no precedent
            # (or index) for a JSONB ->> match here, and the realistic
            # event count per customer is small.
            compensating_events = (
                await db.scalars(select(AuditEvent).where(AuditEvent.event_type == "action.compensating.v1"))
            ).all()
            compensating_since_by_action_id = {
                event.safe_metadata.get("action_id"): event.occurred_at for event in compensating_events
            }

        for action in compensating_actions:
            compensating_since = compensating_since_by_action_id.get(str(action.id))
            if compensating_since is None:
                # Shouldn't happen — apply_transition always records this
                # event on the COMPENSATING transition. Report it rather
                # than silently skip, since it means this script's own
                # assumption about how an Action reaches COMPENSATING is
                # wrong.
                exit_code = 1
                print(
                    f"customer={customer_id} action={action.id} tool={action.tool_name} "
                    "STUCK reason=no_compensating_audit_event",
                    file=sys.stderr,
                )
            elif compensating_since < cutoff:
                exit_code = 1
                age = datetime.now(UTC) - compensating_since
                print(
                    f"customer={customer_id} action={action.id} tool={action.tool_name} "
                    f"STUCK compensating_since={compensating_since.isoformat()} age={age}",
                    file=sys.stderr,
                )
            else:
                print(f"customer={customer_id} action={action.id} tool={action.tool_name} compensating_ok")

    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
