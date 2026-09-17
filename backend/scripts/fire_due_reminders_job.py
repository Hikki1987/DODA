"""FR-TASK-005 reminder-firing job.

A reminder never fires on its own creation — it becomes CONFIRMED first
(application/task_service.confirm_reminder), and this job is what
actually turns a due CONFIRMED reminder into a REMINDER_DUE notification
for whoever requested it, via application/task_service.fire_due_reminders.
No paging/alerting system exists in this project yet (same honest
statement as verify_audit_chain_job.py); this is meant to run on a
schedule (cron/systemd timer) frequently enough that "due" reminders
don't sit unfired for long — how frequently is an operational/hosting
decision (OD-005), not something this script picks for itself.

Iterates customer_ids from UserCustomerIndex — the same deliberately
RLS-free bootstrap table verify_audit_chain_job.py/
find_stuck_running_actions.py already use to discover which customers
exist at all, never for tenant content.
"""

import asyncio
import sys

from sqlalchemy import select

from doda.application.task_service import fire_due_reminders
from doda.db import async_session_factory, tenant_scoped_session
from doda.domain.customer.models import UserCustomerIndex


async def main() -> int:
    async with async_session_factory() as session:
        customer_ids = (await session.scalars(select(UserCustomerIndex.customer_id).distinct())).all()

    total_fired = 0
    for customer_id in customer_ids:
        async with tenant_scoped_session(customer_id) as db:
            fired = await fire_due_reminders(db)

        if fired:
            total_fired += len(fired)
            print(f"customer={customer_id} fired={len(fired)}")

    print(f"total_fired={total_fired} customers_checked={len(customer_ids)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
