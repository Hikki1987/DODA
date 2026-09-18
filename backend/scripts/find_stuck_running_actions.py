"""Stuck-RUNNING Action detector.

`infrastructure/telegram_relay.py`'s own docstring is honest about a gap
it does not close: a crash between a successful connector call and this
process's own commit of the SUCCEEDED/FAILED transition leaves an Action
stuck in RUNNING forever. No code path ever revisits it — redelivery of
the same outbox entry sees `status != READY` and skips it cleanly, which
is correct for avoiding a duplicate send, but also means a stuck Action
is invisible unless someone thinks to look for it.

This script does not attempt to resolve a stuck Action. Deciding how to
safely reconcile against a connector with no request-level idempotency
key (Telegram's Bot API, today's only connector) is a real design
decision — was the message actually sent or not? — not something a
monitoring script should guess at. It only makes the gap observable,
the same "alert is this process's exit status" approach as
verify_audit_chain_job.py, so an operator (or a future reconciliation
job, once that design decision is made) has something to act on instead
of a silently stuck Action.

Discovers every customer to check via `customer_service.list_all_customer_ids`,
same pattern as verify_audit_chain_job.py. For each customer, an Action
still in RUNNING is "stuck" once its own `action.running.v1` audit event
(written by `apply_transition` at the moment it made that transition) is
older than `threshold`.
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta

from _ops_lib import find_actions_stuck_in_status

from doda.application.customer_service import list_all_customer_ids
from doda.db import tenant_scoped_session
from doda.domain.action.models import ActionStatus

DEFAULT_STUCK_THRESHOLD = timedelta(minutes=15)


async def main(threshold: timedelta = DEFAULT_STUCK_THRESHOLD) -> int:
    customer_ids = await list_all_customer_ids()

    cutoff = datetime.now(UTC) - threshold
    exit_code = 0
    for customer_id in customer_ids:
        async with tenant_scoped_session(customer_id) as db:
            pairs = await find_actions_stuck_in_status(
                db, status=ActionStatus.RUNNING, entered_status_event_type="action.running.v1"
            )

        for action, running_since in pairs:
            if running_since is None:
                # Shouldn't happen — apply_transition always records this
                # event on the RUNNING transition. Report it rather than
                # silently skip, since it means this script's own
                # assumption about how an Action reaches RUNNING is wrong.
                exit_code = 1
                print(
                    f"customer={customer_id} action={action.id} tool={action.tool_name} "
                    "STUCK reason=no_running_audit_event",
                    file=sys.stderr,
                )
            elif running_since < cutoff:
                exit_code = 1
                age = datetime.now(UTC) - running_since
                print(
                    f"customer={customer_id} action={action.id} tool={action.tool_name} "
                    f"STUCK running_since={running_since.isoformat()} age={age}",
                    file=sys.stderr,
                )
            else:
                print(f"customer={customer_id} action={action.id} tool={action.tool_name} running_ok")

    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
