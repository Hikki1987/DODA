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

Iterates customer_ids from `UserCustomerIndex`, same pattern as
verify_audit_chain_job.py. For each customer, an Action still in
RUNNING is "stuck" once its own `action.running.v1` audit event (written
by `apply_transition` at the moment it made that transition) is older
than `threshold`.
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from doda.db import async_session_factory, tenant_scoped_session
from doda.domain.action.models import Action, ActionStatus
from doda.domain.audit.models import AuditEvent
from doda.domain.customer.models import UserCustomerIndex

DEFAULT_STUCK_THRESHOLD = timedelta(minutes=15)


async def main(threshold: timedelta = DEFAULT_STUCK_THRESHOLD) -> int:
    async with async_session_factory() as session:
        customer_ids = (await session.scalars(select(UserCustomerIndex.customer_id).distinct())).all()

    cutoff = datetime.now(UTC) - threshold
    exit_code = 0
    for customer_id in customer_ids:
        async with tenant_scoped_session(customer_id) as db:
            running_actions = (
                await db.scalars(select(Action).where(Action.status == ActionStatus.RUNNING))
            ).all()
            if not running_actions:
                continue

            # One query per customer rather than per action: a JSONB ->>
            # match on safe_metadata has no precedent (or index) in this
            # codebase yet, and the realistic number of `action.running.v1`
            # events per customer is small enough that filtering in Python
            # is simpler and just as correct.
            running_events = (
                await db.scalars(select(AuditEvent).where(AuditEvent.event_type == "action.running.v1"))
            ).all()
            running_since_by_action_id = {
                event.safe_metadata.get("action_id"): event.occurred_at for event in running_events
            }

        for action in running_actions:
            running_since = running_since_by_action_id.get(str(action.id))
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
