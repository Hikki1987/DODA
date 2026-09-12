"""End-to-end HTTP tests for the conversation API scaffolding — same
authoritative-chain pattern as test_tasks_api.py (Session -> Workspace
Membership -> RBAC). Also proves the one behavioral claim this
scaffolding makes: a real AI reply never appears (NullAIPort only),
and no message leaks across workspaces (FR-CONV-003).
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.main import app
from tests.integration.conftest import seed_workspace_member


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_headers(session_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


async def test_missing_session_is_rejected(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()
    response = await client.post(f"/v1/workspaces/{member.workspace_id}/conversations", json={})
    assert response.status_code == 401


async def test_no_membership_is_denied(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()
    other = await seed_workspace_member()
    response = await client.post(
        f"/v1/workspaces/{other.workspace_id}/conversations",
        json={},
        headers=_auth_headers(member.session_id),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DENY"


async def test_member_can_start_a_conversation_and_post_a_message(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member()

    create = await client.post(
        f"/v1/workspaces/{member.workspace_id}/conversations",
        json={"title": "Birinchi suhbat"},
        headers=_auth_headers(member.session_id),
    )
    assert create.status_code == 200
    conversation_id = create.json()["id"]

    post = await client.post(
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        json={"content": "Salom, DODA!"},
        headers=_auth_headers(member.session_id),
    )
    assert post.status_code == 200
    messages = post.json()
    assert len(messages) == 2
    assert messages[0]["role"] == "USER"
    assert messages[0]["content"] == "Salom, DODA!"
    assert messages[1]["role"] == "ASSISTANT"
    # The one behavioral guarantee this scaffolding makes: no real model
    # is wired in, so the reply must be NullAIPort's fixed text, never an
    # echo or a fabricated answer.
    assert "hali tanlanmagan" in messages[1]["content"]

    listed = await client.get(
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(member.session_id),
    )
    assert listed.status_code == 200
    assert [m["role"] for m in listed.json()] == ["USER", "ASSISTANT"]


async def test_conversation_list_and_messages_do_not_leak_across_workspaces(
    client: AsyncClient, db_available: bool
) -> None:
    """FR-CONV-003: 'Boshqa workspace konteksti retrieval'da qaytmaydi.'"""
    member = await seed_workspace_member()
    other = await seed_workspace_member()

    create = await client.post(
        f"/v1/workspaces/{member.workspace_id}/conversations",
        json={},
        headers=_auth_headers(member.session_id),
    )
    conversation_id = create.json()["id"]
    await client.post(
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        json={"content": "maxfiy workspace ma'lumoti"},
        headers=_auth_headers(member.session_id),
    )

    other_list = await client.get(
        f"/v1/workspaces/{other.workspace_id}/conversations", headers=_auth_headers(other.session_id)
    )
    assert other_list.status_code == 200
    assert other_list.json() == []

    cross_read = await client.get(
        f"/v1/workspaces/{other.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(other.session_id),
    )
    assert cross_read.status_code == 404
