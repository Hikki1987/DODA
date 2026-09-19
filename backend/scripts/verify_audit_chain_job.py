"""Daily audit hash-chain verification job (FR-AUD-004: "Kunlik
verification job; buzilishda alert").

Walks every customer's audit chain (application/audit_service.verify_audit_chain)
and reports tampering. There is no paging/alerting system in this project yet,
so the "alert" is this process's own exit status and stderr output — intended
to be run on a schedule (cron/systemd timer) that already knows how to alert
on a non-zero exit, the same way the rest of this codebase leans on existing
infrastructure (e.g. CI) rather than inventing a new one.

Discovers every customer to check via `customer_service.list_all_customer_ids`
— the ops-script counterpart of the RLS-free `UserCustomerIndex` bootstrap
table `GET /v1/me/workspaces` uses to answer "which customers does this
user belong to", here read customer-agnostically (distinct customer_id)
purely to discover which customers exist at all, never for tenant content.
"""

import asyncio
import sys

from doda.application.audit_service import verify_audit_chain
from doda.application.customer_service import list_all_customer_ids
from doda.db import tenant_scoped_session


async def main() -> int:
    customer_ids = await list_all_customer_ids()

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
