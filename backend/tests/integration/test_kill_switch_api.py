"""FR-CTL-003 — kill switch, both scopes, over real HTTP against live
Postgres. Includes the drill the TRD calls for by name (12.4 / UC-007):
engage, then measure how fast a new action is actually blocked.
"""

import time
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.application.customer_service import create_customer_with_owner, invite_customer_member
from doda.application.session_service import create_session
from doda.application.workspace_service import add_workspace_member, create_workspace
from doda.db import tenant_scoped_session
from doda.domain.identity.models import AuthStrength, User
from doda.domain.security.roles import CustomerRole
from doda.main import app
from tests.integration.conftest import seed_workspace_member

KILL_SWITCH_SLA_SECONDS = 60.0


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_headers(session_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


async def _propose_action(client: AsyncClient, member, idempotency_key: str):
    return await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "knowledge.read", "risk_level": "R1", "payload": {}},
        headers={**_auth_headers(member.session_id), "Idempotency-Key": idempotency_key},
    )


async def test_workspace_kill_switch_blocks_new_actions_and_disengage_reopens(
    client: AsyncClient, db_available: bool
) -> None:
    admin = await seed_workspace_member(workspace_role="workspace_admin")

    baseline = await _propose_action(client, admin, "before-engage")
    assert baseline.status_code == 200

    engage = await client.post(
        f"/v1/workspaces/{admin.workspace_id}/kill-switch/engage",
        json={"reason": "drill"},
        headers=_auth_headers(admin.session_id),
    )
    assert engage.status_code == 200
    assert engage.json()["engaged"] is True

    blocked = await _propose_action(client, admin, "during-engage")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "KILL_SWITCH_ENGAGED"

    disengage = await client.post(
        f"/v1/workspaces/{admin.workspace_id}/kill-switch/disengage",
        headers=_auth_headers(admin.session_id),
    )
    assert disengage.status_code == 200
    assert disengage.json()["engaged"] is False

    reopened = await _propose_action(client, admin, "after-disengage")
    assert reopened.status_code == 200


async def test_kill_switch_drill_blocks_within_sla(client: AsyncClient, db_available: bool) -> None:
    """UC-007 / 12.4: 'Kill switch <=60s barcha yangi action'ni bloklaydi.'
    Measures actual engage-to-blocked latency rather than assuming it."""
    admin = await seed_workspace_member(workspace_role="workspace_admin")

    engage_started_at = time.monotonic()
    engage = await client.post(
        f"/v1/workspaces/{admin.workspace_id}/kill-switch/engage",
        json={"reason": "drill-timing"},
        headers=_auth_headers(admin.session_id),
    )
    assert engage.status_code == 200

    blocked = await _propose_action(client, admin, "drill-timing-check")
    elapsed = time.monotonic() - engage_started_at

    assert blocked.status_code == 403
    assert elapsed < KILL_SWITCH_SLA_SECONDS


async def test_plain_member_cannot_engage_workspace_kill_switch(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member(workspace_role="member")
    response = await client.post(
        f"/v1/workspaces/{member.workspace_id}/kill-switch/engage",
        json={"reason": "should be denied"},
        headers=_auth_headers(member.session_id),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"


async def test_customer_kill_switch_blocks_every_workspace_under_it(
    client: AsyncClient, db_available: bool
) -> None:
    """Engaging at customer scope must block actions in ALL of that
    customer's workspaces, not just one."""
    owner_user_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        session.add(User(id=owner_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Owner"))
        await session.flush()

        customer, owner_membership = await create_customer_with_owner(
            session, customer_id=customer_id, name="Acme", owner_user_id=owner_user_id, actor_id="user:setup"
        )
        workspace_a = await create_workspace(session, customer_id=customer_id, name="A")
        workspace_b = await create_workspace(session, customer_id=customer_id, name="B")
        await add_workspace_member(
            session, workspace=workspace_a, customer_membership=owner_membership, role="workspace_admin", actor_id="user:setup"
        )
        await add_workspace_member(
            session, workspace=workspace_b, customer_membership=owner_membership, role="workspace_admin", actor_id="user:setup"
        )
        owner_session = await create_session(session, user_id=owner_user_id, auth_strength=AuthStrength.AAL1)

    class _Member:
        def __init__(self, workspace_id, session_id):
            self.workspace_id = workspace_id
            self.session_id = session_id

    member_a = _Member(workspace_a.id, owner_session.id)
    member_b = _Member(workspace_b.id, owner_session.id)

    assert (await _propose_action(client, member_a, "cust-a-before")).status_code == 200
    assert (await _propose_action(client, member_b, "cust-b-before")).status_code == 200

    engage = await client.post(
        f"/v1/customers/{customer_id}/kill-switch/engage",
        json={"reason": "customer-wide drill"},
        headers=_auth_headers(owner_session.id),
    )
    assert engage.status_code == 200

    assert (await _propose_action(client, member_a, "cust-a-during")).status_code == 403
    assert (await _propose_action(client, member_b, "cust-b-during")).status_code == 403

    disengage = await client.post(
        f"/v1/customers/{customer_id}/kill-switch/disengage", headers=_auth_headers(owner_session.id)
    )
    assert disengage.status_code == 200

    assert (await _propose_action(client, member_a, "cust-a-after")).status_code == 200
    assert (await _propose_action(client, member_b, "cust-b-after")).status_code == 200


async def test_plain_member_cannot_engage_customer_kill_switch(
    client: AsyncClient, db_available: bool
) -> None:
    owner_user_id = uuid.uuid4()
    member_user_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        session.add_all(
            [
                User(id=owner_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Owner"),
                User(id=member_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Member"),
            ]
        )
        await session.flush()

        await create_customer_with_owner(
            session, customer_id=customer_id, name="Acme", owner_user_id=owner_user_id, actor_id="user:setup"
        )
        await invite_customer_member(
            session, customer_id=customer_id, user_id=member_user_id, role=CustomerRole.MEMBER, actor_id="user:setup"
        )
        member_session = await create_session(session, user_id=member_user_id, auth_strength=AuthStrength.AAL1)

    response = await client.post(
        f"/v1/customers/{customer_id}/kill-switch/engage",
        json={"reason": "should be denied"},
        headers=_auth_headers(member_session.id),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"
