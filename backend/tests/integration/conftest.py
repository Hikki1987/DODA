import asyncio
import dataclasses
import uuid

import pytest
from sqlalchemy.exc import OperationalError

from doda.application.session_service import create_session
from doda.application.workspace_service import create_workspace
from doda.db import async_session_factory, tenant_scoped_session
from doda.domain.customer.models import Customer, CustomerMembership
from doda.domain.identity.models import AuthStrength, User
from doda.domain.workspace.models import WorkspaceMembership


@pytest.fixture
async def db_available() -> bool:
    """Skip (don't error) when Postgres isn't running locally.

    Catches OSError alongside SQLAlchemy's OperationalError: the most common
    case by far — nothing listening on the port at all — surfaces as a bare
    ConnectionRefusedError (an OSError) straight from asyncpg's connect, which
    SQLAlchemy never gets to wrap. With only OperationalError caught, that case
    produced a screen of identical tracebacks instead of this fixture's whole
    point, one clear "start Postgres" skip message per test (observed for real:
    a crashed local Postgres turned one run into 128 errors).

    Safe in CI despite hiding a dead database: the workflow's postgres/redis
    service containers have health checks, so the job never reaches pytest
    unless they are actually accepting connections.
    """
    try:
        async with async_session_factory() as session:
            await session.connection()
    except (OperationalError, OSError):
        pytest.skip("Postgres not reachable — start it with `docker compose up -d postgres`")
    return True


@pytest.fixture
async def tenant_session(db_available: bool):
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        yield customer_id, session


async def two_racing_sessions(customer_id: uuid.UUID):
    """Open two independent tenant_scoped_session()s for the same customer
    and enter both without committing either — the setup every forced-
    interleaving concurrency test in this directory needs (see
    test_audit_chain_concurrency.py, the original instance of this
    pattern): both "requests" read their target row(s) before either one
    commits, so they genuinely race rather than accidentally serializing.
    Caller reads/mutates via session1/session2, then resolves each side
    with race_outcome or commit_and_return below."""
    cm1 = tenant_scoped_session(customer_id)
    cm2 = tenant_scoped_session(customer_id)
    session1 = await cm1.__aenter__()
    session2 = await cm2.__aenter__()
    return cm1, session1, cm2, session2


async def race_outcome(cm, coro, *, expected_exc: type[Exception]) -> str:
    """Run one side of a two_racing_sessions race where exactly one side is
    expected to win: await `coro`, then commit `cm` and return "ok", or on
    `expected_exc` roll `cm` back and return "rejected". Any other
    exception propagates uncaught."""
    try:
        await coro
    except expected_exc as exc:
        await cm.__aexit__(type(exc), exc, exc.__traceback__)
        return "rejected"
    else:
        await cm.__aexit__(None, None, None)
        return "ok"


async def commit_and_return(cm, coro):
    """Run one side of a two_racing_sessions race where BOTH sides are
    expected to succeed (e.g. idempotent engage, last-write-wins preference
    set) rather than one winning and one losing: await `coro`, commit `cm`,
    and return `coro`'s result."""
    result = await coro
    await cm.__aexit__(None, None, None)
    return result


def assert_worker_still_running_before_signaling(task: asyncio.Task) -> None:
    """Guard for the worker-entrypoint tests that signal their own process.

    Both worker `main()`s register a SIGTERM handler on entry and remove it
    in their `finally`. So if `main()` has already exited when the test fires
    `os.kill(os.getpid(), SIGTERM)`, that signal lands on Python's DEFAULT
    handler and kills the pytest process outright — no failure, no output,
    the run simply vanishes. Observed for real: with Redis stopped, the
    Telegram worker's main() raises on its first command and the test it was
    copied from silently terminated the whole run.

    Calling this first converts that into a normal failure that names the
    real cause (`await task` re-raises it) before any signal is sent.
    """
    if not task.done():
        return
    task.result()  # re-raises whatever made main() exit, if anything
    pytest.fail("worker main() exited on its own before the test could signal it")


@dataclasses.dataclass(frozen=True)
class SeededMember:
    user_id: uuid.UUID
    customer_id: uuid.UUID
    workspace_id: uuid.UUID
    session_id: uuid.UUID


async def seed_workspace_member(
    *,
    workspace_role: str = "member",
    auth_strength: AuthStrength = AuthStrength.AAL1,
) -> SeededMember:
    """Test-only setup: a User with a CustomerMembership + WorkspaceMembership
    on a fresh Customer/Workspace, plus a live Session. Runs inside one
    tenant_scoped_session so the RLS-protected membership rows can actually
    be written — see doda.domain.workspace.models.WorkspaceTenantIndex for
    why customer_id must be chosen up front rather than read back after
    insert.
    """
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as db:
        user = User(oidc_subject_hash=str(uuid.uuid4()), display_name="Test User")
        db.add(user)
        await db.flush()

        db.add(Customer(id=customer_id, name="Test Customer"))
        await db.flush()

        customer_membership = CustomerMembership(customer_id=customer_id, user_id=user.id, role="member")
        db.add(customer_membership)
        await db.flush()

        workspace = await create_workspace(db, customer_id=customer_id, name="Test Workspace")

        db.add(
            WorkspaceMembership(
                customer_id=customer_id,
                customer_membership_id=customer_membership.id,
                workspace_id=workspace.id,
                role=workspace_role,
            )
        )
        await db.flush()

        session_record = await create_session(db, user_id=user.id, auth_strength=auth_strength)

        return SeededMember(
            user_id=user.id,
            customer_id=customer_id,
            workspace_id=workspace.id,
            session_id=session_record.id,
        )
