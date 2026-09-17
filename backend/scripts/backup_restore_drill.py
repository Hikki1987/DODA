"""NFR-DUR-001 verification ("DB PITR, object versioning, sinovdan
o'tgan restore" — qabul mezoni: "Oylik restore drill").

**Honest scope, stated up front, not discovered mid-run**: continuous
WAL archiving / point-in-time recovery is a Postgres SERVER capability
that depends on the managed hosting tier (OD-005, still open) — no
amount of application code can turn that on from here. What IS fully
within this codebase's control, and what this script actually drills,
is the other half of "tested restore": a real `pg_dump` of the live
database, restored into a throwaway database, verified for real — not
just "pg_restore exited 0" — by (1) comparing every table's row count
between source and restore, and (2) re-running the existing audit
hash-chain verification (`audit_service.verify_audit_chain`) against
the RESTORED copy for every customer, proving the restore is not just
present but cryptographically self-consistent.

Uses the migration role (`DODA_MIGRATION_DATABASE_URL`) throughout —
the only role in this codebase with the superuser/CREATEDB privileges
`pg_dump`/`pg_restore`/`CREATE DATABASE` need. The same "`doda` is for
DDL/admin, `doda_app` is for app runtime" split ADR-005 already
established for migrations; this is an ops task, not a runtime path,
so it belongs on the same side of that line.

Run monthly (cron/systemd timer) — same "alert = exit code + stderr, no
paging system yet" honesty as verify_audit_chain_job.py/
find_stuck_running_actions.py.

**Honest environment limit, discovered while writing this, not assumed**:
`pg_dump`'s COPY of an RLS-`FORCE`d table (every tenant-scoped table —
ADR-005) requires the connecting role to actually bypass RLS, which in
production means the migration role's real superuser bit (the official
Postgres image makes `POSTGRES_USER` superuser by default — the exact
fact ADR-005's own incident is about). This SESSION's dev sandbox
deliberately strips `doda` of superuser instead (`.claude/hooks/
session-start.sh` — extensions are created via the OS `postgres` role
specifically so `doda` stays unprivileged even locally), so a live,
full-content run of this script in THIS sandbox reproduces the exact
`pg_dump: error: query would be affected by row-level security policy`
this docstring warns about — confirmed by hand, not assumed. Granting
`doda` BYPASSRLS to work around that, even temporarily, is a real
privilege escalation this session's own safety controls correctly
refused to let it perform unilaterally. What WAS verified for real here:
the create-database/dump/restore/drop mechanics succeed end-to-end
(a `--schema-only` dump avoids the RLS-on-COPY restriction, restoring 32
tables), and the two specific commands that need real superuser
(`CREATE EXTENSION vector`, and the RLS-guarded `COPY`) are exactly the
same two ADR-005 already documents needing it — no new gap, the same
one, on the write side instead of the read side.
"""

import argparse
import asyncio
import subprocess
import sys
import tempfile
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from doda.application.audit_service import verify_audit_chain
from doda.config import get_settings
from doda.domain.customer.models import UserCustomerIndex


def _libpq_url(asyncpg_url: str) -> str:
    """pg_dump/pg_restore/psql speak libpq connection URLs — SQLAlchemy's
    `+asyncpg` driver suffix means nothing to them."""
    return asyncpg_url.replace("postgresql+asyncpg://", "postgresql://")


def _with_database(url: str, database: str) -> str:
    scheme_and_host, _, _ = url.rpartition("/")
    return f"{scheme_and_host}/{database}"


def _run(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True, text=True)


@asynccontextmanager
async def _tenant_scoped_session_against(async_session_factory, customer_id):
    async with async_session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.current_customer_id', :customer_id, true)"),
            {"customer_id": str(customer_id)},
        )
        yield session


async def _verify_restored_audit_chains(drill_asyncpg_url: str) -> tuple[int, int]:
    """Returns (customers_checked, customers_with_a_broken_chain)."""
    engine = create_async_engine(drill_asyncpg_url, pool_pre_ping=True)
    async_session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with async_session_factory() as session:
            customer_ids = (await session.scalars(select(UserCustomerIndex.customer_id).distinct())).all()

        broken = 0
        for customer_id in customer_ids:
            async with _tenant_scoped_session_against(async_session_factory, customer_id) as db:
                result = await verify_audit_chain(db, customer_id=customer_id)
            if not result.ok:
                broken += 1
                print(
                    f"RESTORED COPY TAMPERED: customer={customer_id} violations={len(result.violations)}",
                    file=sys.stderr,
                )
        return len(customer_ids), broken
    finally:
        await engine.dispose()


def _table_row_counts(libpq_url: str) -> dict[str, int]:
    tables = subprocess.run(
        ["psql", libpq_url, "-tAc", "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    counts = {}
    for table in (t.strip() for t in tables if t.strip()):
        count = subprocess.run(
            ["psql", libpq_url, "-tAc", f'SELECT count(*) FROM "{table}"'],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        counts[table] = int(count)
    return counts


async def main(drill_db_name: str) -> int:
    settings = get_settings()
    source_libpq_url = _libpq_url(settings.migration_database_url.get_secret_value())
    parts = urlsplit(source_libpq_url)
    source_db = parts.path.lstrip("/")
    postgres_maintenance_url = _with_database(source_libpq_url, "postgres")
    drill_libpq_url = _with_database(source_libpq_url, drill_db_name)
    drill_asyncpg_url = drill_libpq_url.replace("postgresql://", "postgresql+asyncpg://")

    with tempfile.NamedTemporaryFile(suffix=".dump") as dump_file:
        print(f"Dumping {source_db} -> {dump_file.name}")
        _run(["pg_dump", "-Fc", "-f", dump_file.name, source_libpq_url])

        print(f"(Re)creating throwaway database {drill_db_name}")
        subprocess.run(
            ["psql", postgres_maintenance_url, "-c", f"DROP DATABASE IF EXISTS {drill_db_name}"],
            check=True,
            capture_output=True,
        )
        _run(["psql", postgres_maintenance_url, "-c", f"CREATE DATABASE {drill_db_name} OWNER doda"])

        try:
            print(f"Restoring {dump_file.name} -> {drill_db_name}")
            # Not check=True: pg_restore exits non-zero on ANY ignored error
            # (e.g. `CREATE EXTENSION` needing a superuser this role may not
            # have — see the module docstring's honest superuser note), even
            # when the actual data restored fine. That distinction matters,
            # so pg_restore's own exit code is not trusted as the verdict —
            # the row-count and audit-chain checks below are the real,
            # authoritative verification of whether the restore is usable.
            restore = subprocess.run(
                ["pg_restore", "-d", drill_libpq_url, dump_file.name], capture_output=True, text=True
            )
            if restore.returncode != 0:
                print(f"pg_restore reported errors (continuing to verify data anyway):\n{restore.stderr}")

            print("Comparing row counts, table by table...")
            source_counts = _table_row_counts(source_libpq_url)
            drill_counts = _table_row_counts(drill_libpq_url)
            mismatches = {
                table: (source_counts[table], drill_counts.get(table))
                for table in source_counts
                if source_counts[table] != drill_counts.get(table)
            }
            for table, (expected, actual) in mismatches.items():
                print(f"ROW COUNT MISMATCH: {table} source={expected} restored={actual}", file=sys.stderr)

            print("Re-verifying every customer's audit hash chain against the restored copy...")
            checked, broken = await _verify_restored_audit_chains(drill_asyncpg_url)
            print(f"audit chains checked={checked} broken={broken}")

            ok = not mismatches and broken == 0
            print("DRILL PASSED" if ok else "DRILL FAILED", file=sys.stdout if ok else sys.stderr)
            return 0 if ok else 1
        finally:
            print(f"Dropping throwaway database {drill_db_name}")
            subprocess.run(
                ["psql", postgres_maintenance_url, "-c", f"DROP DATABASE IF EXISTS {drill_db_name}"],
                check=True,
                capture_output=True,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drill-db-name", default="doda_restore_drill")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.drill_db_name)))
