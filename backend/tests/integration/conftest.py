import uuid

import pytest
from sqlalchemy.exc import OperationalError

from doda.db import async_session_factory, tenant_scoped_session


@pytest.fixture
async def db_available() -> bool:
    try:
        async with async_session_factory() as session:
            await session.connection()
    except OperationalError:
        pytest.skip("Postgres not reachable — start it with `docker compose up -d postgres`")
    return True


@pytest.fixture
async def tenant_session(db_available: bool):
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        yield customer_id, session
