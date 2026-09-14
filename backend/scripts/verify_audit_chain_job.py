"""Daily audit hash-chain verification job (FR-AUD-004: "Kunlik
verification job; buzilishda alert").

Walks every customer's audit chain (application/audit_service.verify_audit_chain)
and reports tampering. There is no paging/alerting system in this project yet,
so the "alert" is this process's own exit status and stderr output — intended
to be run on a schedule (cron/systemd timer) that already knows how to alert
on a non-zero exit, the same way the rest of this codebase leans on existing
infrastructure (e.g. CI) rather than inventing a new one.

Iterates customer_ids from `UserCustomerIndex` — the same deliberately
RLS-free bootstrap table `GET /v1/me/workspaces` uses to answer "which
customers does this user belong to" without a chicken-and-egg RLS lookup;
here it is read customer-agnostically (distinct customer_id) purely to
discover which customers exist at all, never for tenant content.
"""

import asyncio
import sys

from sqlalchemy import select

from doda.application.audit_service import verify_audit_chain
from doda.db import async_session_factory, tenant_scoped_session
from doda.domain.customer.models import UserCustomerIndex


async def main() -> int:
    # `get_session()` (db.py) is a bare async generator meant for FastAPI's
    # `Depends(get_session)`, not `async with` — it isn't decorated with
    # `@asynccontextmanager` the way `tenant_scoped_session` is. This job
    # runs outside any request, so it goes straight to the session factory,
    # same as `get_session` itself does internally.
    async with async_session_factory() as session:
        customer_ids = (await session.scalars(select(UserCustomerIndex.customer_id).distinct())).all()

    exit_code = 0
    for customer_id in customer_ids:
        async with tenant_scoped_session(customer_id) as db:
            result = await verify_audit_chain(db, customer_id=customer_id)

        if result.ok:
            print(f"customer={customer_id} ok checked={result.checked_count}")
        else:
            exit_code = 1
            print(
                f"customer={customer_id} TAMPERED checked={result.checked_count} "
                f"violations={len(result.violations)}",
                file=sys.stderr,
            )
            for violation in result.violations:
                print(f"  event={violation.event_id} reason={violation.reason}", file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
