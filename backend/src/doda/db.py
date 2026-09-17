"""Database engine/session wiring.

Tenant isolation is enforced on two independent layers (ADR-005, NFR-ISO-001/002):
repository-level `customer_id` scoping (application code) AND PostgreSQL
row-level security driven by a transaction-local GUC (`app.current_customer_id`).
Neither layer substitutes for the other.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from doda.config import Settings, get_settings


def _build_engine(settings: Settings) -> AsyncEngine:
    """A pure function of `Settings` (rather than inlined at module scope)
    so `tests/unit/test_db_pool_config.py` can construct an engine from
    arbitrary pool-size settings and inspect it, without needing to
    reload this module or touch the process-wide `engine` singleton
    below."""
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )


_settings = get_settings()

engine = _build_engine(_settings)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def tenant_scoped_session(customer_id: UUID) -> AsyncGenerator[AsyncSession, None]:
    """Yield a session whose transaction has the tenant GUC set for RLS policies.

    Every request that touches tenant-scoped tables must go through this,
    never through a bare session — see CLAUDE.md dependency rules.
    """
    async with async_session_factory() as session, session.begin():
        # SET LOCAL does not accept bind parameters (it's not a regular
        # DML statement); set_config() is a normal function call and
        # does, so it is the only safe way to pass the value in.
        await session.execute(
            text("SELECT set_config('app.current_customer_id', :customer_id, true)"),
            {"customer_id": str(customer_id)},
        )
        yield session
