# ADR-005: PostgreSQL RLS as tenant isolation's second, independent layer

**Status:** Accepted (TRD 6.4) — implemented, tested, and once
**actually failed in production-shaped conditions** (see Incident below)

## Context

NFR-ISO-001 requires zero cross-customer/workspace data visibility.
Relying solely on the application remembering to filter every query by
`customer_id` (NFR-ISO-002) is a single point of failure: one missed
filter in one query, anywhere in the codebase, ever, is a full
tenant-isolation breach with no other safety net.

## Decision

Every tenant-scoped table has `FORCE ROW LEVEL SECURITY` with a policy
keyed on a transaction-local Postgres GUC, `app.current_customer_id`, set
by `tenant_scoped_session()` (`db.py`) at the start of every tenant-scoped
transaction. This must be a genuinely independent second layer enforced by
the database engine itself — not a restatement of the application-layer
filter — so that even a repository-layer bug which forgets the
`customer_id` filter is still blocked by Postgres refusing to return rows
outside the current transaction's tenant context.

`tests/test_rls_coverage.py` mechanically verifies every table with a
`customer_id` column has `FORCE ROW LEVEL SECURITY` enabled, with three
named, deliberate exceptions (`KNOWN_RLS_EXEMPT_TABLES`):
`workspace_tenant_index` and `user_customer_index` — both RLS-free
bootstrap tables solving the same "how do you look up a tenant before you
know its tenant" chicken-and-egg problem, one level apart
(workspace→customer, then user→customer) — and `outbox_messages` (the
relay worker needs a platform-wide view — see ADR-003).

## Consequences

**Positive**
- Defense in depth: a repository-layer mistake alone cannot leak
  cross-tenant data, because Postgres itself still enforces the boundary.
- Mechanically checked in CI (`test_rls_coverage.py`), not just documented
  convention — a new tenant-scoped table without `FORCE ROW LEVEL
  SECURITY` fails the build.

**Negative — and this is the important one**
- **This layer is trivially and silently defeated if the application ever
  connects as a Postgres superuser or any role with `BYPASSRLS`** —
  superusers always skip row security regardless of `FORCE ROW LEVEL
  SECURITY`. This is Postgres's own, unconfigurable rule, not a setting.

## Incident: this "second layer" did nothing in every fresh/CI/production environment

The first time this project's CI ran the test suite against a genuinely
fresh (empty-volume) Postgres container, `test_tenant_isolation.py` failed
with a real cross-tenant data leak: one customer could see another
customer's workspaces. The cause: the official Postgres Docker image
always creates the role named by `POSTGRES_USER` as a **superuser** — this
project's application was connecting directly as that same bootstrap role
(`doda`). So every table's `FORCE ROW LEVEL SECURITY` was silently a
no-op in any fresh environment (CI, and — had it shipped this way — real
production), leaving the application-layer `customer_id` filter as the
*only* actual protection, contradicting the "independent second layer"
this ADR requires. This had never been visible in local development only
because that one hand-configured environment already happened to have a
non-superuser role pre-provisioned.

**Fix:** two roles, one source of truth
(`infra/postgres-init/01-create-app-role.sql`): `doda` (superuser) is now
used *only* for Alembic migrations (`DODA_MIGRATION_DATABASE_URL`), which
genuinely need superuser for `CREATE EXTENSION`. The application itself
connects as a new, deliberately non-superuser `doda_app` role
(`DODA_DATABASE_URL`, created `NOSUPERUSER NOBYPASSRLS`) with only the
SELECT/INSERT/UPDATE/DELETE grants it actually needs (via `ALTER DEFAULT
PRIVILEGES`, so future migrations' tables are covered automatically).
`test_rls_coverage.py` now includes
`test_app_connects_as_a_role_that_cannot_bypass_row_level_security`,
which checks the connected role's `rolsuper`/`rolbypassrls` flags directly
against real Postgres — this exact class of regression is now caught by
CI every time, not just in a lucky local environment.

## Lesson

An "independent second layer" of defense is only as independent as the
database role actually executing it. Verify the role, not just the
policy.
