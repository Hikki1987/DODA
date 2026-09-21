"""NFR-ISO-003 — "AI kontekst izolyatsiyasi: Prompt kontekstida boshqa
workspace matni bo'lmaydi."

This is provable by construction: `conversation_service._messages_to_history`
is built exclusively from `list_messages(session, conversation_id=...)`, and
`Message` itself carries no `workspace_id` column to leak through — there is
no query path by which another conversation's rows could end up in one turn's
history. But it had never been positively proven end-to-end, and
FR-CONV-003's existing cross-workspace test
(`test_conversation_list_and_messages_do_not_leak_across_workspaces`) uses two
DIFFERENT customers, where RLS's own `customer_id` filter already blocks the
read before context assembly is ever reached — the same distinction
`test_cross_workspace_record_access.py` exists to cover for tasks/actions.

This test uses the strict case RLS cannot help with — two workspaces under
the SAME customer — and inspects the actual `history` handed to the model
gateway (not just the HTTP response) to prove one workspace's message content
never reaches a gateway call made on a sibling workspace's behalf, across
multiple turns.
"""

import typing
import uuid

import pytest
from httpx import ASGITransport, AsyncClient, Response

from doda.ai.types import ChatMode, ChatTurn, Completed, GatewayEvent, GatewayUsage, TextDelta, ToolSpec
from doda.application.session_service import create_session
from doda.application.workspace_service import create_workspace
from doda.db import tenant_scoped_session
from doda.domain.customer.models import Customer, CustomerMembership
from doda.domain.identity.models import AuthStrength, User
from doda.domain.workspace.models import WorkspaceMembership
from doda.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_headers(session_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


async def _post_message(client: AsyncClient, url: str, *, headers: dict[str, str], content: str) -> Response:
    async with client.stream(
        "POST", url, json={"content": content, "mode": "STANDARD"}, headers=headers
    ) as response:
        await response.aread()
        return response


async def _seed_two_workspaces_one_customer() -> dict[str, typing.Any]:
    """One customer, two workspaces, two users — each a member of one
    workspace only. Same shape as test_cross_workspace_record_access.py's
    helper: both rows carry the same customer_id, so RLS alone cannot
    separate them — only the application's own workspace_id/conversation_id
    scoping can."""
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as db:
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
                    role="workspace_admin",
                ),
                WorkspaceMembership(
                    customer_id=customer_id,
                    customer_membership_id=membership_b.id,
                    workspace_id=workspace_b.id,
                    role="workspace_admin",
                ),
            ]
        )
        await db.flush()

        session_a = await create_session(db, user_id=user_a.id, auth_strength=AuthStrength.AAL1)
        session_b = await create_session(db, user_id=user_b.id, auth_strength=AuthStrength.AAL1)

        return {
            "workspace_a": workspace_a.id,
            "workspace_b": workspace_b.id,
            "session_a": session_a.id,
            "session_b": session_b.id,
        }


class _HistoryRecordingGateway:
    """Records the `history` it was actually invoked with, per call — lets
    the test inspect exactly what content reached the model, not just
    whether the HTTP response looked right."""

    def __init__(self) -> None:
        self.received_histories: list[list[ChatTurn]] = []

    async def stream_chat(
        self,
        *,
        model: str,
        mode: ChatMode,
        instructions: str,
        history: list[ChatTurn],
        tools: list[ToolSpec],
        max_output_tokens: int,
        response_schema: dict[str, typing.Any] | None = None,
    ) -> typing.AsyncIterator[GatewayEvent]:
        del model, mode, instructions, tools, max_output_tokens, response_schema
        self.received_histories.append(list(history))
        yield TextDelta(text="ok")
        yield Completed(usage=GatewayUsage(input_tokens=1, output_tokens=1), finish_reason="stop")


async def test_a_sibling_workspaces_message_content_never_reaches_the_model_context(
    client: AsyncClient, db_available: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = await _seed_two_workspaces_one_customer()
    gateway = _HistoryRecordingGateway()
    monkeypatch.setattr(
        "doda.application.conversation_service.get_gateway", lambda provider, settings: gateway
    )

    create_a = await client.post(
        f"/v1/workspaces/{seeded['workspace_a']}/conversations",
        json={},
        headers=_auth_headers(seeded["session_a"]),
    )
    assert create_a.status_code == 200
    conversation_a = create_a.json()["id"]
    secret = "A workspace'ining maxfiy narx strategiyasi: 15% oshirish"
    first_a = await _post_message(
        client,
        f"/v1/workspaces/{seeded['workspace_a']}/conversations/{conversation_a}/messages",
        headers=_auth_headers(seeded["session_a"]),
        content=secret,
    )
    assert first_a.status_code == 200

    create_b = await client.post(
        f"/v1/workspaces/{seeded['workspace_b']}/conversations",
        json={},
        headers=_auth_headers(seeded["session_b"]),
    )
    assert create_b.status_code == 200
    conversation_b = create_b.json()["id"]

    first_b = await _post_message(
        client,
        f"/v1/workspaces/{seeded['workspace_b']}/conversations/{conversation_b}/messages",
        headers=_auth_headers(seeded["session_b"]),
        content="B uchun oddiy savol",
    )
    assert first_b.status_code == 200

    # A second turn in B, AFTER A's secret already exists in the database —
    # proves this isn't just "the first call happened to run before A wrote
    # anything", but that every call scoped to B's conversation excludes A's
    # content, turn after turn.
    second_b = await _post_message(
        client,
        f"/v1/workspaces/{seeded['workspace_b']}/conversations/{conversation_b}/messages",
        headers=_auth_headers(seeded["session_b"]),
        content="yana bir savol",
    )
    assert second_b.status_code == 200

    assert len(gateway.received_histories) == 3  # A's 1 turn + B's 2 turns
    b_histories = gateway.received_histories[1:]
    assert len(b_histories) == 2
    for history in b_histories:
        for turn in history:
            assert secret not in turn.content
