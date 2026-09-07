"""Live PostgreSQL RLS test — NFR-ISO-001 acceptance ('Live PostgreSQL RLS testlari').

Requires a running Postgres with migrations applied (see README: docker
compose up + alembic upgrade head). Skips automatically if unreachable, so
`pytest` stays usable without infra for unit-only runs.
"""

import uuid

import pytest
from sqlalchemy.exc import OperationalError

from doda.db import async_session_factory, tenant_scoped_session
from doda.domain.workspace.models import Workspace


@pytest.fixture
async def db_available() -> bool:
    try:
        async with async_session_factory() as session:
            await session.connection()
    except OperationalError:
        pytest.skip("Postgres not reachable — start it with `docker compose up -d postgres`")
    return True


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
