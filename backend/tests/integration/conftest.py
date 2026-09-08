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
