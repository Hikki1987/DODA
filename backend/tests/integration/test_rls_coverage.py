"""NFR-ISO-001 / ADR-005: every tenant-scoped table must carry FORCE ROW
LEVEL SECURITY as the second, defense-in-depth layer of tenant isolation
(repository-level customer_id filtering being the first). This is a
regression net for the RLS layer itself: it does not test that policies
are *correct* (test_tenant_isolation.py does that behaviorally), only that
nobody adds a new customer_id-bearing table in a future migration and
forgets to enable+force RLS on it, silently downgrading a two-layer
tenant boundary to one.
"""

from sqlalchemy import text

from doda.db import async_session_factory

# Base.metadata only contains tables whose model module has actually been
# imported somewhere. Importing every domain's models here — the same list
# migrations/env.py imports for autogenerate — is required so this test
# can't silently go blind on a domain that happens not to be imported by
# whatever else pytest collected first.
from doda.domain.action import approval as _action_approval_models  # noqa: F401
from doda.domain.action import models as _action_models  # noqa: F401
from doda.domain.audit import models as _audit_models  # noqa: F401
from doda.domain.base import Base
from doda.domain.customer import models as _customer_models  # noqa: F401
from doda.domain.identity import models as _identity_models  # noqa: F401
from doda.domain.notification import models as _notification_models  # noqa: F401
from doda.domain.outbox import models as _outbox_models  # noqa: F401
from doda.domain.security import kill_switch as _security_kill_switch_models  # noqa: F401
from doda.domain.task import models as _task_models  # noqa: F401
from doda.domain.workspace import models as _workspace_models  # noqa: F401

# All deliberate, documented exceptions:
# - workspace_tenant_index: a bootstrap table solving RLS's own
#   chicken-and-egg problem (you need customer_id to pass RLS, but this
#   table's whole job is telling you a workspace's customer_id). See
#   doda.domain.workspace.models.WorkspaceTenantIndex.
# - user_customer_index: the same bootstrap pattern one level up — you
#   need a customer_id to pass RLS on customer_memberships, but this
#   table's whole job is telling you which customers a user belongs to.
#   See doda.domain.customer.models.UserCustomerIndex.
# - outbox_messages: the relay is a platform-level process that must see
#   every customer's pending messages to deliver them, and the payload is
#   already-derived event data, not raw tenant content. See
#   doda.domain.outbox.models.OutboxMessage.
KNOWN_RLS_EXEMPT_TABLES = {"workspace_tenant_index", "user_customer_index", "outbox_messages"}


def _tables_with_customer_id() -> set[str]:
    return {table.name for table in Base.metadata.tables.values() if "customer_id" in table.columns}


async def test_every_customer_scoped_table_has_forced_row_level_security(db_available: bool) -> None:
    tenant_tables = _tables_with_customer_id() - KNOWN_RLS_EXEMPT_TABLES
    assert tenant_tables, "expected at least one customer_id-bearing table to check"

    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "select relname, relrowsecurity, relforcerowsecurity "
                "from pg_class where relname = any(:names) and relkind = 'r'"
            ),
            {"names": list(tenant_tables)},
        )
        rows = {row.relname: (row.relrowsecurity, row.relforcerowsecurity) for row in result}

    missing = tenant_tables - rows.keys()
    assert not missing, f"customer_id-bearing table(s) not found in the database: {sorted(missing)}"

    not_forced = [name for name, (enabled, forced) in rows.items() if not (enabled and forced)]
    assert not not_forced, (
        f"table(s) missing FORCE ROW LEVEL SECURITY: {sorted(not_forced)} "
        "— add it in a migration, or add to KNOWN_RLS_EXEMPT_TABLES with a "
        "documented reason if it's a deliberate exception."
    )


async def test_known_exempt_tables_are_still_real_tables_not_stale_entries(db_available: bool) -> None:
    """Guards the exemption list itself: if workspace_tenant_index is ever
    renamed or dropped, this must fail loudly rather than let the exemption
    silently stop meaning anything."""
    all_table_names = {table.name for table in Base.metadata.tables.values()}
    stale = KNOWN_RLS_EXEMPT_TABLES - all_table_names
    assert not stale, f"KNOWN_RLS_EXEMPT_TABLES references table(s) that no longer exist: {sorted(stale)}"


async def test_app_connects_as_a_role_that_cannot_bypass_row_level_security(db_available: bool) -> None:
    """FORCE ROW LEVEL SECURITY (checked above) is worthless if the role the
    application actually connects as is a PostgreSQL superuser, or has been
    granted BYPASSRLS directly — both unconditionally skip every RLS policy
    regardless of FORCE. This is not hypothetical: the official postgres
    Docker image always creates its POSTGRES_USER as a superuser, which is
    exactly the role docker-compose.yml's app previously connected as. A
    genuinely fresh Postgres container (first exercised by CI, never by the
    long-lived local dev container) exposed real cross-tenant data leakage
    in test_tenant_isolation.py before doda_app (infra/postgres-init) and
    this test existed. See README.md's "Ikki xil DB roli" section.
    """
    async with async_session_factory() as session:
        row = (
            await session.execute(
                text("select rolsuper, rolbypassrls from pg_roles where rolname = current_user")
            )
        ).one()

    assert not row.rolsuper, (
        "the app's DODA_DATABASE_URL connects as a PostgreSQL superuser — "
        "superusers always bypass row security, so every FORCE ROW LEVEL "
        "SECURITY table is silently unprotected. Point DODA_DATABASE_URL "
        "at the unprivileged doda_app role instead (see infra/postgres-init)."
    )
    assert not row.rolbypassrls, (
        "the app's DODA_DATABASE_URL connects as a role with the BYPASSRLS "
        "attribute — remove it; the app role must be subject to RLS like "
        "any ordinary tenant, not exempt from it."
    )
