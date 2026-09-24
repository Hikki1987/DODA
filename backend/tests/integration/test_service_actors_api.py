"""End-to-end HTTP tests for FR-AUTH-009's Service Actor credential flow —
minting, authenticating, and the two invariants from 2.2's role table: a
Service Actor's own maximum risk level is R2, and it may never consume an
approval, full stop.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.domain.identity.models import AuthStrength
from doda.main import app
from tests.integration.conftest import SeededMember, seed_workspace_member


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


async def _create_credential(client: AsyncClient, owner: SeededMember, name: str = "ci-bot") -> dict:
    response = await client.post(
        f"/v1/customers/{owner.customer_id}/service-actors",
        json={"name": name},
        headers=_auth_headers(owner.session_id),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _authenticate(client: AsyncClient, secret: str) -> uuid.UUID:
    response = await client.post("/v1/auth/service-actor", json={"secret": secret})
    assert response.status_code == 200, response.text
    return uuid.UUID(response.json()["session_id"])


async def _add_to_workspace(client: AsyncClient, owner: SeededMember, user_id: uuid.UUID) -> None:
    members = await client.get(
        f"/v1/customers/{owner.customer_id}/members", headers=_auth_headers(owner.session_id)
    )
    assert members.status_code == 200, members.text
    membership_id = next(row["membership_id"] for row in members.json() if row["user_id"] == str(user_id))
    response = await client.post(
        f"/v1/workspaces/{owner.workspace_id}/members",
        json={"customer_membership_id": membership_id, "role": "member"},
        headers=_auth_headers(owner.session_id),
    )
    assert response.status_code == 200, response.text


async def test_creating_a_credential_returns_the_secret_exactly_once(
    client: AsyncClient, db_available: bool
) -> None:
    owner = await seed_workspace_member(customer_role="customer_owner")
    created = await _create_credential(client, owner)
    assert created["secret"]
    assert created["name"] == "ci-bot"

    listed = await client.get(
        f"/v1/customers/{owner.customer_id}/service-actors", headers=_auth_headers(owner.session_id)
    )
    assert listed.status_code == 200
    [entry] = listed.json()
    assert "secret" not in entry
    assert entry["id"] == created["id"]


async def test_a_plain_member_may_not_mint_a_credential(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member(customer_role="member")
    response = await client.post(
        f"/v1/customers/{member.customer_id}/service-actors",
        json={"name": "ci-bot"},
        headers=_auth_headers(member.session_id),
    )
    assert response.status_code == 403


async def test_authenticating_with_the_minted_secret_succeeds(
    client: AsyncClient, db_available: bool
) -> None:
    owner = await seed_workspace_member(customer_role="customer_owner")
    created = await _create_credential(client, owner)

    session_id = await _authenticate(client, created["secret"])
    assert session_id != owner.session_id


async def test_authenticating_with_a_wrong_secret_is_rejected(
    client: AsyncClient, db_available: bool
) -> None:
    response = await client.post("/v1/auth/service-actor", json={"secret": "not-a-real-secret"})
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_revoked_credential_can_no_longer_authenticate(client: AsyncClient, db_available: bool) -> None:
    owner = await seed_workspace_member(customer_role="customer_owner")
    created = await _create_credential(client, owner)

    revoke = await client.delete(
        f"/v1/customers/{owner.customer_id}/service-actors/{created['id']}",
        headers=_auth_headers(owner.session_id),
    )
    assert revoke.status_code == 204

    response = await client.post("/v1/auth/service-actor", json={"secret": created["secret"]})
    assert response.status_code == 401


async def test_service_actor_may_propose_an_auto_approved_action_but_not_a_high_risk_one(
    client: AsyncClient, db_available: bool
) -> None:
    owner = await seed_workspace_member(customer_role="customer_owner")
    created = await _create_credential(client, owner)
    session_id = await _authenticate(client, created["secret"])

    machine_user_id = uuid.UUID(
        next(
            row["user_id"]
            for row in (
                await client.get(
                    f"/v1/customers/{owner.customer_id}/members", headers=_auth_headers(owner.session_id)
                )
            ).json()
            if row["user_id"] != str(owner.user_id)
        )
    )
    await _add_to_workspace(client, owner, machine_user_id)

    low_risk = await client.post(
        f"/v1/workspaces/{owner.workspace_id}/actions",
        json={"tool_name": "knowledge.read", "risk_level": "R1", "payload": {}},
        headers=_auth_headers(session_id, "svc-low-risk-1"),
    )
    assert low_risk.status_code == 200, low_risk.text
    assert low_risk.json()["action"]["status"] == "READY"

    high_risk = await client.post(
        f"/v1/workspaces/{owner.workspace_id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "boss@example.com"}},
        headers=_auth_headers(session_id, "svc-high-risk-1"),
    )
    assert high_risk.status_code == 403
    assert high_risk.json()["code"] == "SERVICE_ACTOR_RISK_LEVEL_EXCEEDED"


async def test_service_actor_may_never_consume_an_approval(client: AsyncClient, db_available: bool) -> None:
    """A Service Actor cannot even reach AWAITING_APPROVAL on its own
    (test_service_actor_may_propose_an_auto_approved_action_but_not_a_high_risk_one
    proves that), so this proves the second, independent layer: a Service
    Actor session added as workspace_admin to a workspace where a HUMAN
    proposed an R3 action still cannot consume that action's approval —
    2.2's invariant is unconditional, not merely "no role can reach it"."""
    owner = await seed_workspace_member(customer_role="customer_owner", auth_strength=AuthStrength.AAL2)
    created = await _create_credential(client, owner)
    session_id = await _authenticate(client, created["secret"])

    machine_user_id = uuid.UUID(
        next(
            row["user_id"]
            for row in (
                await client.get(
                    f"/v1/customers/{owner.customer_id}/members", headers=_auth_headers(owner.session_id)
                )
            ).json()
            if row["user_id"] != str(owner.user_id)
        )
    )
    # workspace_admin, not member: proves the DENY comes from actor_kind,
    # not merely from lacking ROLES_THAT_MAY_APPROVE_ANOTHER_ACTORS_ACTION.
    members = await client.get(
        f"/v1/customers/{owner.customer_id}/members", headers=_auth_headers(owner.session_id)
    )
    membership_id = next(
        row["membership_id"] for row in members.json() if row["user_id"] == str(machine_user_id)
    )
    add = await client.post(
        f"/v1/workspaces/{owner.workspace_id}/members",
        json={"customer_membership_id": membership_id, "role": "workspace_admin"},
        headers=_auth_headers(owner.session_id),
    )
    assert add.status_code == 200, add.text

    propose = await client.post(
        f"/v1/workspaces/{owner.workspace_id}/actions",
        json={"tool_name": "email.send", "risk_level": "R3", "payload": {"to": "boss@example.com"}},
        headers=_auth_headers(owner.session_id, "svc-approve-1"),
    )
    assert propose.status_code == 200, propose.text
    approval_id = propose.json()["approval"]["id"]
    nonce = propose.json()["approval"]["nonce"]

    consume = await client.post(
        f"/v1/workspaces/{owner.workspace_id}/approvals/{approval_id}/consume",
        json={"nonce": nonce},
        headers=_auth_headers(session_id),
    )
    assert consume.status_code == 403
    assert consume.json()["code"] == "DENY"
