"""End-to-end HTTP tests for the action API — proves the authoritative
chain (section 10) actually gates the endpoints, not just that the
application-layer functions do when called directly (test_action_lifecycle.py
already covers that). Every test here goes through real HTTP + a real
Postgres-backed Session/Membership chain.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.domain.identity.models import AuthStrength
from doda.main import app
from tests.integration.conftest import seed_workspace_member


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_headers(session_id: uuid.UUID, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {session_id}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


async def test_missing_session_is_rejected(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()
    response = await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "knowledge.read", "risk_level": "R1", "payload": {}},
        headers={"Idempotency-Key": "no-auth-1"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_session_with_no_membership_is_denied(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()
    other_workspace = await seed_workspace_member()  # different customer/workspace entirely

    response = await client.post(
        f"/v1/workspaces/{other_workspace.workspace_id}/actions",
        json={"tool_name": "knowledge.read", "risk_level": "R1", "payload": {}},
        headers=_auth_headers(member.session_id, "no-membership-1"),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"


async def test_low_risk_action_is_auto_ready_end_to_end(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()

    response = await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "knowledge.read", "risk_level": "R1", "payload": {"query": "hi"}},
        headers=_auth_headers(member.session_id, "e2e-r1-1"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["action"]["status"] == "READY"
    assert body["approval"] is None


async def test_action_trace_id_matches_the_http_requests_own_trace_id(
    client: AsyncClient, db_available: bool
) -> None:
    """NFR-OBS-001 ("100% action/approval trace korrelyatsiyasi"):
    TraceIdMiddleware documents that a request's trace_id is meant to
    double as the Action's own trace_id — this proves the endpoint
    actually does that, both with a client-supplied X-Trace-Id and with
    one minted server-side, rather than generating an unrelated uuid4()
    that would silently decorrelate the HTTP-level trace from the domain
    audit trail it triggers.
    """
    member = await seed_workspace_member()
    client_trace_id = str(uuid.uuid4())

    response = await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "knowledge.read", "risk_level": "R1", "payload": {"query": "hi"}},
        headers={**_auth_headers(member.session_id, "e2e-trace-1"), "X-Trace-Id": client_trace_id},
    )
    assert response.status_code == 200
    assert response.headers["X-Trace-Id"] == client_trace_id
    assert response.json()["action"]["trace_id"] == client_trace_id

    # No client-supplied header: the server-minted trace_id must still be
    # the one that ends up on the Action, not a second, disconnected uuid4.
    no_header_response = await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "knowledge.read", "risk_level": "R1", "payload": {"query": "hi"}},
        headers=_auth_headers(member.session_id, "e2e-trace-2"),
    )
    assert no_header_response.status_code == 200
    assert no_header_response.json()["action"]["trace_id"] == no_header_response.headers["X-Trace-Id"]


async def test_duplicate_idempotency_key_returns_same_action(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()
    payload = {"tool_name": "knowledge.read", "risk_level": "R1", "payload": {"query": "hi"}}
    headers = _auth_headers(member.session_id, "e2e-idem-1")

    first = await client.post(f"/v1/workspaces/{member.workspace_id}/actions", json=payload, headers=headers)
    second = await client.post(f"/v1/workspaces/{member.workspace_id}/actions", json=payload, headers=headers)

    assert first.json()["action"]["id"] == second.json()["action"]["id"]


async def test_high_risk_action_requires_step_up_before_approval_consumption(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member(auth_strength=AuthStrength.AAL1)

    submit = await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "boss@example.com"}},
        headers=_auth_headers(member.session_id, "e2e-r3-1"),
    )
    body = submit.json()
    assert body["action"]["status"] == "AWAITING_APPROVAL"
    assert body["approval"] is not None

    consume = await client.post(
        f"/v1/workspaces/{member.workspace_id}/approvals/{body['approval']['id']}/consume",
        json={"nonce": body["approval"]["nonce"]},
        headers=_auth_headers(member.session_id),
    )
    assert consume.status_code == 403
    assert consume.json()["code"] == "STEP_UP_REQUIRED"


async def test_high_risk_action_self_approval_succeeds_with_fresh_mfa(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member(auth_strength=AuthStrength.AAL2)

    submit = await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "boss@example.com"}},
        headers=_auth_headers(member.session_id, "e2e-r3-2"),
    )
    body = submit.json()

    consume = await client.post(
        f"/v1/workspaces/{member.workspace_id}/approvals/{body['approval']['id']}/consume",
        json={"nonce": body["approval"]["nonce"]},
        headers=_auth_headers(member.session_id),
    )
    assert consume.status_code == 200
    assert consume.json()["status"] == "READY"


async def test_wrong_nonce_is_rejected_over_http(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member(auth_strength=AuthStrength.AAL2)

    submit = await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "boss@example.com"}},
        headers=_auth_headers(member.session_id, "e2e-r3-3"),
    )
    approval = submit.json()["approval"]

    consume = await client.post(
        f"/v1/workspaces/{member.workspace_id}/approvals/{approval['id']}/consume",
        json={"nonce": "wrong-nonce"},
        headers=_auth_headers(member.session_id),
    )
    assert consume.status_code == 409
    assert consume.json()["code"] == "APPROVAL_INVALID"


async def test_approval_from_another_workspace_is_not_found(client: AsyncClient, db_available: bool) -> None:
    member_a = await seed_workspace_member(auth_strength=AuthStrength.AAL2)
    member_b = await seed_workspace_member(auth_strength=AuthStrength.AAL2)

    submit = await client.post(
        f"/v1/workspaces/{member_a.workspace_id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "boss@example.com"}},
        headers=_auth_headers(member_a.session_id, "e2e-cross-1"),
    )
    approval_id = submit.json()["approval"]["id"]

    # member_b is authenticated and has real membership — just in a
    # different workspace/customer, so they pass the workspace-membership
    # gate on their own path but the approval itself belongs to a different
    # tenant. 404, not 403: existence of another tenant's approval id is
    # not something to confirm either way (10.1: sezgir tafsilot ko'rsatilmaydi).
    consume = await client.post(
        f"/v1/workspaces/{member_b.workspace_id}/approvals/{approval_id}/consume",
        json={"nonce": "irrelevant"},
        headers=_auth_headers(member_b.session_id),
    )
    assert consume.status_code == 404


async def test_workspace_admin_can_approve_a_members_action(client: AsyncClient, db_available: bool) -> None:
    # Two separate memberships in the SAME workspace: proposer (member) and
    # approver (workspace_admin). seed_workspace_member always creates a
    # fresh workspace, so build this scenario by hand instead of reusing it
    # verbatim for the second identity.
    import doda.db as doda_db
    from doda.application.session_service import create_session
    from doda.application.workspace_service import create_workspace
    from doda.domain.customer.models import Customer, CustomerMembership
    from doda.domain.identity.models import User
    from doda.domain.workspace.models import WorkspaceMembership

    customer_id = uuid.uuid4()
    async with doda_db.tenant_scoped_session(customer_id) as db:
        proposer = User(oidc_subject_hash=str(uuid.uuid4()), display_name="Proposer")
        approver = User(oidc_subject_hash=str(uuid.uuid4()), display_name="Approver")
        db.add_all([proposer, approver])
        await db.flush()

        db.add(Customer(id=customer_id, name="Shared Customer"))
        await db.flush()

        proposer_membership = CustomerMembership(customer_id=customer_id, user_id=proposer.id, role="member")
        approver_membership = CustomerMembership(customer_id=customer_id, user_id=approver.id, role="member")
        db.add_all([proposer_membership, approver_membership])
        await db.flush()

        workspace = await create_workspace(db, customer_id=customer_id, name="Shared Workspace")

        db.add_all(
            [
                WorkspaceMembership(
                    customer_id=customer_id,
                    customer_membership_id=proposer_membership.id,
                    workspace_id=workspace.id,
                    role="member",
                ),
                WorkspaceMembership(
                    customer_id=customer_id,
                    customer_membership_id=approver_membership.id,
                    workspace_id=workspace.id,
                    role="workspace_admin",
                ),
            ]
        )
        await db.flush()

        proposer_session = await create_session(db, user_id=proposer.id, auth_strength=AuthStrength.AAL1)
        approver_session = await create_session(db, user_id=approver.id, auth_strength=AuthStrength.AAL2)

    submit = await client.post(
        f"/v1/workspaces/{workspace.id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "x@example.com"}},
        headers=_auth_headers(proposer_session.id, "e2e-admin-approve-1"),
    )
    approval = submit.json()["approval"]

    consume = await client.post(
        f"/v1/workspaces/{workspace.id}/approvals/{approval['id']}/consume",
        json={"nonce": approval["nonce"]},
        headers=_auth_headers(approver_session.id),
    )
    assert consume.status_code == 200
    assert consume.json()["status"] == "READY"


async def test_bare_customer_owner_can_approve_a_members_action_over_http(
    client: AsyncClient, db_available: bool
) -> None:
    """CLAUDE.md flagged this as an open question after the get_workspace_context
    fix (which only had test coverage for archive/manage-members, not R3
    approval): does a customer_owner with NO WorkspaceMembership row at all
    also pass authorize_consume_approval's ROLES_THAT_MAY_APPROVE_ANOTHER_ACTORS_ACTION
    check? authorize_consume_approval reads context.role, which
    get_workspace_context already resolves to WORKSPACE_ADMIN for any
    customer_owner — so this should already work. Proving it here rather
    than assuming it, since it was never actually exercised end-to-end."""
    import doda.db as doda_db
    from doda.application.customer_service import create_customer_with_owner
    from doda.application.session_service import create_session
    from doda.application.workspace_service import add_workspace_member, create_workspace
    from doda.domain.customer.models import CustomerMembership
    from doda.domain.identity.models import User

    customer_id = uuid.uuid4()
    owner_user_id = uuid.uuid4()
    async with doda_db.tenant_scoped_session(customer_id) as db:
        proposer = User(oidc_subject_hash=str(uuid.uuid4()), display_name="Proposer")
        owner = User(id=owner_user_id, oidc_subject_hash=str(uuid.uuid4()), display_name="Owner")
        db.add_all([proposer, owner])
        await db.flush()

        _customer, owner_membership = await create_customer_with_owner(
            db, customer_id=customer_id, name="Acme", owner_user_id=owner_user_id, actor_id="user:setup"
        )
        proposer_membership = CustomerMembership(customer_id=customer_id, user_id=proposer.id, role="member")
        db.add(proposer_membership)
        await db.flush()

        workspace = await create_workspace(db, customer_id=customer_id, name="Shared Workspace")
        # Only the proposer gets an actual WorkspaceMembership row — the
        # owner never does, on purpose.
        await add_workspace_member(
            db,
            workspace=workspace,
            customer_membership=proposer_membership,
            role="member",
            actor_id="user:setup",
        )

        proposer_session = await create_session(db, user_id=proposer.id, auth_strength=AuthStrength.AAL1)
        owner_session = await create_session(db, user_id=owner_user_id, auth_strength=AuthStrength.AAL2)

    submit = await client.post(
        f"/v1/workspaces/{workspace.id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "x@example.com"}},
        headers=_auth_headers(proposer_session.id, "e2e-owner-approve-1"),
    )
    approval = submit.json()["approval"]

    consume = await client.post(
        f"/v1/workspaces/{workspace.id}/approvals/{approval['id']}/consume",
        json={"nonce": approval["nonce"]},
        headers=_auth_headers(owner_session.id),
    )
    assert consume.status_code == 200
    assert consume.json()["status"] == "READY"


async def test_same_idempotency_key_in_different_workspaces_does_not_collide(
    client: AsyncClient, db_available: bool
) -> None:
    """Security regression: Action.idempotency_key used to be unique per
    customer_id ONLY, so two different workspaces under the same customer
    choosing the same caller-supplied key collided onto the SAME Action
    row — propose_action's idempotent-replay path would then hand
    Workspace A's caller Workspace B's action payload and pending
    approval nonce. Fixed by scoping the uniqueness (and the replay
    lookup) to (customer_id, workspace_id, idempotency_key) — each
    workspace must get its OWN action for the same key, never a shared
    one, let alone a leaked one.
    """
    import doda.db as doda_db
    from doda.application.session_service import create_session
    from doda.application.workspace_service import create_workspace
    from doda.domain.customer.models import Customer, CustomerMembership
    from doda.domain.identity.models import User
    from doda.domain.workspace.models import WorkspaceMembership

    customer_id = uuid.uuid4()
    shared_key = "same-key-both-workspaces"
    async with doda_db.tenant_scoped_session(customer_id) as db:
        user_a = User(oidc_subject_hash=str(uuid.uuid4()), display_name="A")
        user_b = User(oidc_subject_hash=str(uuid.uuid4()), display_name="B")
        db.add_all([user_a, user_b])
        await db.flush()

        db.add(Customer(id=customer_id, name="Shared Customer"))
        await db.flush()

        membership_a = CustomerMembership(customer_id=customer_id, user_id=user_a.id, role="member")
        membership_b = CustomerMembership(customer_id=customer_id, user_id=user_b.id, role="member")
        db.add_all([membership_a, membership_b])
        await db.flush()

        workspace_a = await create_workspace(db, customer_id=customer_id, name="A")
        workspace_b = await create_workspace(db, customer_id=customer_id, name="B")
        db.add_all(
            [
                WorkspaceMembership(
                    customer_id=customer_id,
                    customer_membership_id=membership_a.id,
                    workspace_id=workspace_a.id,
                    role="member",
                ),
                WorkspaceMembership(
                    customer_id=customer_id,
                    customer_membership_id=membership_b.id,
                    workspace_id=workspace_b.id,
                    role="member",
                ),
            ]
        )
        await db.flush()

        session_a = await create_session(db, user_id=user_a.id, auth_strength=AuthStrength.AAL1)
        session_b = await create_session(db, user_id=user_b.id, auth_strength=AuthStrength.AAL1)

    submit_a = await client.post(
        f"/v1/workspaces/{workspace_a.id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "a-secret@example.com"}},
        headers=_auth_headers(session_a.id, shared_key),
    )
    assert submit_a.status_code == 200
    action_a = submit_a.json()["action"]

    submit_b = await client.post(
        f"/v1/workspaces/{workspace_b.id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "b-secret@example.com"}},
        headers=_auth_headers(session_b.id, shared_key),
    )
    assert submit_b.status_code == 200
    action_b = submit_b.json()["action"]

    # The critical assertion: two SEPARATE actions, not the same row
    # replayed across workspaces.
    assert action_a["id"] != action_b["id"]
    assert action_a["workspace_id"] == str(workspace_a.id)
    assert action_b["workspace_id"] == str(workspace_b.id)

    # And B's approval nonce must never surface via A's replay of the
    # same key (the actual leak this regression test guards against).
    approval_b = submit_b.json()["approval"]
    replay_a = await client.post(
        f"/v1/workspaces/{workspace_a.id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "a-secret@example.com"}},
        headers=_auth_headers(session_a.id, shared_key),
    )
    assert replay_a.json()["action"]["id"] == action_a["id"]
    if replay_a.json()["approval"] is not None:
        assert replay_a.json()["approval"]["nonce"] != approval_b["nonce"]


async def test_list_workspace_actions_returns_all_actions_in_the_workspace(
    client: AsyncClient, db_available: bool
) -> None:
    """There was no way to list actions in a workspace at all before this —
    only propose and get-by-id — the same class of discoverability gap
    GET /v1/me/workspaces closed one level up."""
    member = await seed_workspace_member()
    for key in ("list-a", "list-b"):
        await client.post(
            f"/v1/workspaces/{member.workspace_id}/actions",
            json={"tool_name": "knowledge.read", "risk_level": "R1", "payload": {}},
            headers=_auth_headers(member.session_id, key),
        )

    response = await client.get(
        f"/v1/workspaces/{member.workspace_id}/actions", headers=_auth_headers(member.session_id)
    )
    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_list_workspace_actions_filters_by_status(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member(auth_strength=AuthStrength.AAL2)
    await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "knowledge.read", "risk_level": "R1", "payload": {}},
        headers=_auth_headers(member.session_id, "status-filter-ready"),
    )
    await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "x@example.com"}},
        headers=_auth_headers(member.session_id, "status-filter-awaiting"),
    )

    response = await client.get(
        f"/v1/workspaces/{member.workspace_id}/actions?status=AWAITING_APPROVAL",
        headers=_auth_headers(member.session_id),
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "AWAITING_APPROVAL"


async def test_list_workspace_actions_does_not_leak_another_workspaces_actions(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member()
    other = await seed_workspace_member()
    await client.post(
        f"/v1/workspaces/{other.workspace_id}/actions",
        json={"tool_name": "knowledge.read", "risk_level": "R1", "payload": {}},
        headers=_auth_headers(other.session_id, "cross-workspace-list"),
    )

    response = await client.get(
        f"/v1/workspaces/{member.workspace_id}/actions", headers=_auth_headers(member.session_id)
    )
    assert response.status_code == 200
    assert response.json() == []


async def test_a_consumed_approval_cannot_be_consumed_again_over_http(
    client: AsyncClient, db_available: bool
) -> None:
    """9.2's one-time nonce, through the endpoint a caller actually replays.
    The wrong-nonce rejection above covers the mismatch branch; the
    already-spent branch — the one a retry or a double-click produces — had
    no test, and it is the half that matters for "bir martalik"."""
    member = await seed_workspace_member(auth_strength=AuthStrength.AAL2)

    submit = await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "boss@example.com"}},
        headers=_auth_headers(member.session_id, "e2e-r3-replay-1"),
    )
    approval = submit.json()["approval"]
    url = f"/v1/workspaces/{member.workspace_id}/approvals/{approval['id']}/consume"

    first = await client.post(
        url, json={"nonce": approval["nonce"]}, headers=_auth_headers(member.session_id)
    )
    assert first.status_code == 200
    assert first.json()["status"] == "READY"

    replay = await client.post(
        url, json={"nonce": approval["nonce"]}, headers=_auth_headers(member.session_id)
    )
    assert replay.status_code == 409
    assert replay.json()["code"] == "APPROVAL_INVALID"


async def test_the_approval_nonce_is_never_returned_again_after_the_proposal(
    client: AsyncClient, db_available: bool
) -> None:
    """9.2's nonce is a one-time credential, and ApprovalOut.nonce's own
    docstring says it is "returned once, to the same caller who is shown the
    pending-approval preview". Nothing enforced that: if a future field were
    added to ActionOut, or a listing started embedding its approval, the nonce
    would start leaking to every workspace member on a plain GET — and no test
    would have noticed. Asserted against the whole serialized response rather
    than a field name, so it catches the nonce arriving under any shape.
    """
    member = await seed_workspace_member(auth_strength=AuthStrength.AAL2)

    submit = await client.post(
        f"/v1/workspaces/{member.workspace_id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "boss@example.com"}},
        headers=_auth_headers(member.session_id, "nonce-exposure-1"),
    )
    body = submit.json()
    nonce = body["approval"]["nonce"]
    assert nonce  # the proposal response is the one place it may appear
    action_id = body["action"]["id"]

    single = await client.get(
        f"/v1/workspaces/{member.workspace_id}/actions/{action_id}",
        headers=_auth_headers(member.session_id),
    )
    assert single.status_code == 200
    assert nonce not in single.text

    listed = await client.get(
        f"/v1/workspaces/{member.workspace_id}/actions", headers=_auth_headers(member.session_id)
    )
    assert listed.status_code == 200
    assert nonce not in listed.text

    audit = await client.get(
        f"/v1/workspaces/{member.workspace_id}/audit", headers=_auth_headers(member.session_id)
    )
    assert audit.status_code == 200
    # 12.3: it must not have been written into the audit trail either.
    assert nonce not in audit.text
