"""FR-AUD-002 — audit viewer, both scopes, matching 10.2's actual matrix:
Member sees only their own actions; WorkspaceAdmin sees the whole
workspace; CustomerOwner/Auditor see the whole customer.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.application.customer_service import create_customer_with_owner, invite_customer_member
from doda.application.session_service import create_session
from doda.application.workspace_service import add_workspace_member
from doda.db import tenant_scoped_session
from doda.domain.identity.models import AuthStrength, User
from doda.domain.security.roles import CustomerRole
from doda.main import app
from tests.integration.conftest import seed_workspace_member


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


async def test_workspace_admin_sees_every_actors_events(client: AsyncClient, db_available: bool) -> None:
    admin = await seed_workspace_member(workspace_role="workspace_admin")
    await _propose_action(client, admin, "admin-view-1")

    response = await client.get(
        f"/v1/workspaces/{admin.workspace_id}/audit", headers=_auth_headers(admin.session_id)
    )
    assert response.status_code == 200
    event_types = {e["event_type"] for e in response.json()}
    assert "action.proposed.v1" in event_types


async def test_member_only_sees_their_own_actions(client: AsyncClient, db_available: bool) -> None:
    """10.2: Member's audit access is 'O'z amallarini' — not the whole
    workspace, even though they can see the workspace's actions themselves."""
    # Two members in one workspace: reuse seed_workspace_member's customer
    # by inviting a second identity into it.
    first = await seed_workspace_member(workspace_role="member")

    async with tenant_scoped_session(first.customer_id) as session:
        second_user = User(id=uuid.uuid4(), oidc_subject_hash=str(uuid.uuid4()), display_name="Second")
        session.add(second_user)
        await session.flush()
        second_customer_membership = await invite_customer_member(
            session,
            customer_id=first.customer_id,
            user_id=second_user.id,
            role=CustomerRole.MEMBER,
            actor_id="user:setup",
        )
        from doda.domain.workspace.models import Workspace

        workspace = await session.get(Workspace, first.workspace_id)
        await add_workspace_member(
            session,
            workspace=workspace,
            customer_membership=second_customer_membership,
            role="member",
            actor_id="user:setup",
        )
        second_session = await create_session(
            session, user_id=second_user.id, auth_strength=AuthStrength.AAL1
        )

    await _propose_action(client, first, "member-view-mine")

    class _Second:
        workspace_id = first.workspace_id
        session_id = second_session.id

    await _propose_action(client, _Second(), "member-view-other")

    response = await client.get(
        f"/v1/workspaces/{first.workspace_id}/audit", headers=_auth_headers(first.session_id)
    )
    assert response.status_code == 200
    for event in response.json():
        assert event["actor_id"] == f"user:{first.user_id}"


async def test_customer_owner_sees_whole_customer_audit(client: AsyncClient, db_available: bool) -> None:
    owner_user_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        session.add(User(id=owner_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Owner"))
        await session.flush()
        await create_customer_with_owner(
            session, customer_id=customer_id, name="Acme", owner_user_id=owner_user_id, actor_id="user:setup"
        )
        owner_session = await create_session(session, user_id=owner_user_id, auth_strength=AuthStrength.AAL1)

    response = await client.get(f"/v1/customers/{customer_id}/audit", headers=_auth_headers(owner_session.id))
    assert response.status_code == 200
    # customer.created.v1 must be visible — proves customer-scoped (not
    # workspace-scoped) events are reachable here.
    event_types = {e["event_type"] for e in response.json()}
    assert "customer.created.v1" in event_types


async def test_customer_member_cannot_view_customer_wide_audit(
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
            session,
            customer_id=customer_id,
            user_id=member_user_id,
            role=CustomerRole.MEMBER,
            actor_id="user:setup",
        )
        member_session = await create_session(
            session, user_id=member_user_id, auth_strength=AuthStrength.AAL1
        )

    response = await client.get(
        f"/v1/customers/{customer_id}/audit", headers=_auth_headers(member_session.id)
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"


async def test_auditor_can_view_but_cannot_engage_kill_switch(
    client: AsyncClient, db_available: bool
) -> None:
    """Cross-check that Auditor's read-only access (2.2) really is
    read-only: they can view audit, but authorize_engage_customer_kill_switch
    (a write) must still deny them."""
    owner_user_id = uuid.uuid4()
    auditor_user_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        session.add_all(
            [
                User(id=owner_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Owner"),
                User(id=auditor_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Auditor"),
            ]
        )
        await session.flush()
        await create_customer_with_owner(
            session, customer_id=customer_id, name="Acme", owner_user_id=owner_user_id, actor_id="user:setup"
        )
        await invite_customer_member(
            session,
            customer_id=customer_id,
            user_id=auditor_user_id,
            role=CustomerRole.AUDITOR,
            actor_id="user:setup",
        )
        auditor_session = await create_session(
            session, user_id=auditor_user_id, auth_strength=AuthStrength.AAL1
        )

    view_response = await client.get(
        f"/v1/customers/{customer_id}/audit", headers=_auth_headers(auditor_session.id)
    )
    assert view_response.status_code == 200

    engage_response = await client.post(
        f"/v1/customers/{customer_id}/kill-switch/engage",
        json={"reason": "auditor should not be able to do this"},
        headers=_auth_headers(auditor_session.id),
    )
    assert engage_response.status_code == 403
    assert engage_response.json()["code"] == "DENY"


async def test_viewing_audit_is_itself_audited(client: AsyncClient, db_available: bool) -> None:
    """FR-AUD-002 acceptance: 'eksport audit qilinadi.'"""
    admin = await seed_workspace_member(workspace_role="workspace_admin")

    first_view = await client.get(
        f"/v1/workspaces/{admin.workspace_id}/audit", headers=_auth_headers(admin.session_id)
    )
    assert first_view.status_code == 200

    second_view = await client.get(
        f"/v1/workspaces/{admin.workspace_id}/audit", headers=_auth_headers(admin.session_id)
    )
    event_types = [e["event_type"] for e in second_view.json()]
    assert "audit.viewed.v1" in event_types


async def test_trace_id_filter_finds_exactly_one_requests_own_events(
    client: AsyncClient, db_available: bool
) -> None:
    """NFR-OBS-001's actual operator lookup, end to end over HTTP: given a
    request's X-Trace-Id, the audit viewer must return that request's events
    and nothing else.

    test_actions_api.py already pins the writing half (an Action carries the
    HTTP request's own trace_id rather than a fresh uuid4). This is the
    reading half — the `?trace_id=` filter on list_audit_events, which had no
    coverage at all, so the correlation was only ever half-proved.
    """
    admin = await seed_workspace_member(workspace_role="workspace_admin")
    traced = str(uuid.uuid4())

    first = await client.post(
        f"/v1/workspaces/{admin.workspace_id}/actions",
        json={"tool_name": "knowledge.read", "risk_level": "R1", "payload": {}},
        headers={
            **_auth_headers(admin.session_id),
            "Idempotency-Key": "trace-filter-1",
            "X-Trace-Id": traced,
        },
    )
    assert first.status_code == 200
    # A second, differently-traced request in the same workspace: the filter
    # has to exclude it, otherwise "returns this request's events" would pass
    # for a filter that silently ignores its argument.
    await _propose_action(client, admin, "trace-filter-2")

    response = await client.get(
        f"/v1/workspaces/{admin.workspace_id}/audit",
        params={"trace_id": traced},
        headers=_auth_headers(admin.session_id),
    )
    assert response.status_code == 200
    events = response.json()
    assert events, "the traced request's own audit events should be findable by its trace_id"
    assert {e["trace_id"] for e in events} == {traced}


async def test_event_type_filter_narrows_to_that_type(client: AsyncClient, db_available: bool) -> None:
    """The other never-exercised filter on the same endpoint. Proposing an
    action writes more than one event type, so this also shows the filter
    excludes rather than merely returning everything."""
    admin = await seed_workspace_member(workspace_role="workspace_admin")
    await _propose_action(client, admin, "event-type-filter-1")

    unfiltered = await client.get(
        f"/v1/workspaces/{admin.workspace_id}/audit", headers=_auth_headers(admin.session_id)
    )
    assert len({e["event_type"] for e in unfiltered.json()}) > 1

    response = await client.get(
        f"/v1/workspaces/{admin.workspace_id}/audit",
        params={"event_type": "action.proposed.v1"},
        headers=_auth_headers(admin.session_id),
    )
    assert response.status_code == 200
    events = response.json()
    assert events
    assert {e["event_type"] for e in events} == {"action.proposed.v1"}
