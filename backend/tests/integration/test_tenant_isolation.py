"""Live PostgreSQL RLS test — NFR-ISO-001 acceptance ('Live PostgreSQL RLS testlari').

Requires a running Postgres with migrations applied (see README: docker
compose up + alembic upgrade head). Skips automatically if unreachable, so
`pytest` stays usable without infra for unit-only runs.
"""

import uuid

import pytest
from sqlalchemy.exc import DBAPIError

from doda.db import tenant_scoped_session
from doda.domain.workspace.models import Workspace


async def test_workspace_query_is_isolated_by_tenant_guc(db_available: bool) -> None:
    customer_a, customer_b = uuid.uuid4(), uuid.uuid4()

    async with tenant_scoped_session(customer_a) as session:
        session.add(Workspace(customer_id=customer_a, name="A's workspace"))
        await session.flush()

    async with tenant_scoped_session(customer_b) as session:
        session.add(Workspace(customer_id=customer_b, name="B's workspace"))
        await session.flush()

    async with tenant_scoped_session(customer_a) as session:
        result = await session.execute(Workspace.__table__.select())
        visible_names = {row.name for row in result}

    assert visible_names == {"A's workspace"}


async def test_a_workspace_cannot_be_created_without_a_tenant(db_available: bool) -> None:
    """FR-WKS-002: "Workspace CustomerId'ga bog'lanadi; global workspace
    mavjud emas" — a documented invariant, never behaviorally checked
    before this: the column IS declared NOT NULL and IS covered by the
    generic FORCE ROW LEVEL SECURITY sweep (test_rls_coverage.py), but
    neither of those tests actually attempts the one thing the TRD wording
    forbids — a workspace with no customer at all. The model's own type
    hint (Mapped[uuid.UUID], not Optional) says this shouldn't be
    constructible, but SQLAlchemy's generated __init__ doesn't enforce
    that at runtime — the same gap a stray None from calling code could
    slip through — so this exercises the real DB-level guarantee rather
    than trusting the type hint alone. Raises
    DBAPIError either way: this session's tenant GUC (customer_id) can
    never equal NULL, so RLS's WITH CHECK rejects the row before the NOT
    NULL constraint even gets a turn — proven by inspecting the live
    schema (`\\d workspace_workspaces`) rather than assumed, but the two
    layers are redundant on purpose (ADR-005), so either one failing
    alone would already satisfy this test.
    """
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        session.add(Workspace(customer_id=None, name="No Tenant"))
        with pytest.raises(DBAPIError):
            await session.flush()
