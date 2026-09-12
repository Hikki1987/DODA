"""End-to-end HTTP tests for the conversation API — same authoritative-
chain pattern as test_tasks_api.py (Session -> Workspace Membership ->
RBAC). No real provider credential is configured in this test
environment, so every turn runs against `doda.ai.port.NullModelGateway`
(see its own docstring) — these tests prove the HTTP/SSE contract and
FR-CONV-003's workspace isolation, not any real provider's behavior
(that is `tests/unit/test_{openai,gemini,claude}_gateway.py`'s job).
"""

import json
import typing
import uuid

import pytest
from httpx import ASGITransport, AsyncClient, Response

from doda.ai.errors import ModelProviderError, ModelTimeoutError
from doda.ai.types import (
    ChatMode,
    ChatRole,
    ChatTurn,
    Completed,
    GatewayEvent,
    GatewayUsage,
    Provider,
    TextDelta,
    ToolCallReady,
    ToolCallRequest,
    ToolSpec,
)
from doda.application import ai_budget_service, ai_provider_settings_service
from doda.db import tenant_scoped_session
from doda.domain.ai_usage.models import AIBudgetLedger
from doda.main import app
from tests.integration.conftest import seed_workspace_member


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_headers(session_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip("\n").split("\n\n"):
        if not block:
            continue
        event_line, data_line = block.split("\n", 1)
        events.append((event_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: "))))
    return events


async def _post_message(
    client: AsyncClient, url: str, *, headers: dict[str, str], content: str, mode: str = "STANDARD"
) -> Response:
    """A successful turn is a 200 SSE stream; an authz/validation failure
    (never reaches `stream_message`) is a plain JSON error response, same
    as every other endpoint — callers check `response.status_code` before
    assuming the body is SSE."""
    async with client.stream(
        "POST", url, json={"content": content, "mode": mode}, headers=headers
    ) as response:
        await response.aread()
        return response


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
    assert create.json()["pinned_provider"] is None

    post = await _post_message(
        client,
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(member.session_id),
        content="Salom, DODA!",
    )
    assert post.status_code == 200
    assert post.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(post.text)

    # NullModelGateway (no provider configured in this test environment)
    # always yields exactly one text delta then completes — FR-CONV-008's
    # "safe degradation", never a fabricated-looking answer.
    assert events[0][0] == "text"
    assert "hali tanlanmagan" in events[0][1]["text"]
    assert events[-1][0] == "done"
    final_message = events[-1][1]["message"]
    assert final_message["role"] == "ASSISTANT"
    assert "hali tanlanmagan" in final_message["content"]
    assert final_message["finish_reason"] == "stop"

    listed = await client.get(
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(member.session_id),
    )
    assert listed.status_code == 200
    roles = [m["role"] for m in listed.json()]
    assert roles == ["USER", "ASSISTANT"]
    assert listed.json()[0]["content"] == "Salom, DODA!"


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
    await _post_message(
        client,
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(member.session_id),
        content="maxfiy workspace ma'lumoti",
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

    cross_post = await _post_message(
        client,
        f"/v1/workspaces/{other.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(other.session_id),
        content="should never be accepted",
    )
    assert cross_post.status_code == 404


async def test_switching_a_conversations_provider_pins_it_without_touching_other_conversations(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member()

    create = await client.post(
        f"/v1/workspaces/{member.workspace_id}/conversations",
        json={},
        headers=_auth_headers(member.session_id),
    )
    conversation_id = create.json()["id"]

    other_create = await client.post(
        f"/v1/workspaces/{member.workspace_id}/conversations",
        json={},
        headers=_auth_headers(member.session_id),
    )
    other_conversation_id = other_create.json()["id"]

    switch = await client.post(
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/provider",
        json={"provider": "CLAUDE", "model": "claude-sonnet-5"},
        headers=_auth_headers(member.session_id),
    )
    assert switch.status_code == 200
    assert switch.json()["pinned_provider"] == "CLAUDE"
    assert switch.json()["pinned_model"] == "claude-sonnet-5"

    unaffected = await client.get(
        f"/v1/workspaces/{member.workspace_id}/conversations", headers=_auth_headers(member.session_id)
    )
    by_id = {c["id"]: c for c in unaffected.json()}
    assert by_id[other_conversation_id]["pinned_provider"] is None


class _TwoRoundFailingGateway:
    """Round 1: a real text delta plus a read-tool call (so the caller
    already received >=1 SSE chunk before anything goes wrong) — round 2:
    a provider error. Proves `post_conversation_message`'s claim that a
    failure AFTER the first byte becomes one final `event: error` SSE
    frame rather than an aborted connection, module docstring's second
    bullet."""

    def __init__(self) -> None:
        self.calls = 0

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
        del model, mode, instructions, history, tools, max_output_tokens, response_schema
        self.calls += 1
        if self.calls == 1:
            yield TextDelta(text="salom")
            yield ToolCallReady(
                call=ToolCallRequest(call_id="c1", name="list_my_open_tasks", arguments_json="{}")
            )
            yield Completed(usage=GatewayUsage(input_tokens=1, output_tokens=1), finish_reason="tool_calls")
        else:
            raise ModelProviderError("boom", status_code=500)


async def test_a_mid_stream_provider_failure_ends_with_one_sse_error_frame_and_commits_the_partial_turn(
    client: AsyncClient, db_available: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_gateway = _TwoRoundFailingGateway()
    monkeypatch.setattr(
        "doda.application.conversation_service.get_gateway", lambda provider, settings: fake_gateway
    )

    member = await seed_workspace_member()
    create = await client.post(
        f"/v1/workspaces/{member.workspace_id}/conversations",
        json={},
        headers=_auth_headers(member.session_id),
    )
    conversation_id = create.json()["id"]

    post = await _post_message(
        client,
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(member.session_id),
        content="ishlarimni ko'rsat",
    )
    # The failure happens on round 2, AFTER round 1's text chunk already
    # reached the client — headers are long gone by then, so this must
    # stay 200 with the error folded into the SSE body, never a 5xx.
    assert post.status_code == 200
    events = _parse_sse(post.text)
    assert events[0] == ("text", {"text": "salom"})
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "AI_STREAM_ERROR"
    assert fake_gateway.calls == 2

    # The turn's transaction still commits what really happened: the
    # user's message, the assistant's tool-call turn, and the read tool's
    # result — but no final "done" assistant message, since the turn
    # never reached one.
    listed = await client.get(
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(member.session_id),
    )
    roles = [m["role"] for m in listed.json()]
    assert roles == ["USER", "ASSISTANT", "TOOL"]
    assert listed.json()[1]["tool_name"] == "list_my_open_tasks"

    # And the budget reservation for the whole (multi-round) estimate is
    # reconciled down to the single round that actually ran — never left
    # as a phantom reservation that silently eats the next real request's
    # headroom (conversation_service.stream_message's generalized
    # `except Exception:` clause).
    async with tenant_scoped_session(member.customer_id) as db:
        ledger = await db.get(AIBudgetLedger, (member.customer_id, ai_budget_service.current_year_month()))
        assert ledger is not None
        assert ledger.reserved_cents == 0
        assert ledger.actual_cents >= 0


class _ScriptedGateway:
    """Replays one event script per round; the LAST script repeats for
    any round beyond the list (so a script of one "always calls a tool"
    round naturally exercises `stream_message`'s ai_max_tool_rounds
    exhaustion path without needing a custom, low `ai_max_tool_rounds`)."""

    def __init__(self, rounds: list[list[GatewayEvent]]) -> None:
        self._rounds = rounds
        self.calls = 0

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
        del model, mode, instructions, history, tools, max_output_tokens, response_schema
        script = self._rounds[min(self.calls, len(self._rounds) - 1)]
        self.calls += 1
        for event in script:
            yield event


async def test_a_read_tool_call_feeds_its_result_back_for_a_real_second_round(
    client: AsyncClient, db_available: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = _ScriptedGateway(
        [
            [
                ToolCallReady(
                    call=ToolCallRequest(call_id="c1", name="list_my_open_tasks", arguments_json="{}")
                ),
                Completed(usage=GatewayUsage(input_tokens=1, output_tokens=1), finish_reason="tool_calls"),
            ],
            [
                TextDelta(text="ishlaringiz yo'q ekan"),
                Completed(usage=GatewayUsage(input_tokens=1, output_tokens=1), finish_reason="stop"),
            ],
        ]
    )
    monkeypatch.setattr(
        "doda.application.conversation_service.get_gateway", lambda provider, settings: gateway
    )

    member = await seed_workspace_member()
    create = await client.post(
        f"/v1/workspaces/{member.workspace_id}/conversations",
        json={},
        headers=_auth_headers(member.session_id),
    )
    conversation_id = create.json()["id"]

    post = await _post_message(
        client,
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(member.session_id),
        content="ishlarim bormi?",
    )
    assert post.status_code == 200
    events = _parse_sse(post.text)
    assert events[-1][0] == "done"
    assert events[-1][1]["message"]["content"] == "ishlaringiz yo'q ekan"
    assert gateway.calls == 2

    listed = await client.get(
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(member.session_id),
    )
    roles = [m["role"] for m in listed.json()]
    assert roles == ["USER", "ASSISTANT", "TOOL", "ASSISTANT"]
    assert listed.json()[2]["tool_call_id"] == "c1"
    assert listed.json()[3]["finish_reason"] == "stop"


async def test_a_write_tool_call_ends_the_turn_and_creates_a_real_pending_action(
    client: AsyncClient, db_available: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = _ScriptedGateway(
        [
            [
                ToolCallReady(
                    call=ToolCallRequest(
                        call_id="c1",
                        name="telegram_send_message",
                        arguments_json=json.dumps({"chat_id": "123", "text": "salom"}),
                    )
                ),
                Completed(usage=GatewayUsage(input_tokens=1, output_tokens=1), finish_reason="tool_calls"),
            ]
        ]
    )
    monkeypatch.setattr(
        "doda.application.conversation_service.get_gateway", lambda provider, settings: gateway
    )

    member = await seed_workspace_member()
    create = await client.post(
        f"/v1/workspaces/{member.workspace_id}/conversations",
        json={},
        headers=_auth_headers(member.session_id),
    )
    conversation_id = create.json()["id"]

    post = await _post_message(
        client,
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(member.session_id),
        content="telegramga xabar yubor",
    )
    assert post.status_code == 200
    events = _parse_sse(post.text)
    # A write tool call NEVER executes inline and NEVER completes the
    # turn with a model-generated "done" — the turn ends with exactly one
    # deterministic status message, same shape every time regardless of
    # what the model said.
    assert events[-1][0] == "done"
    final_content = events[-1][1]["message"]["content"]
    assert "inson tasdig'isiz bajarilmaydi" in final_content
    # Only one round happened — a write call stops the loop immediately,
    # it is never followed by a second gateway call "finishing" the turn.
    assert gateway.calls == 1

    actions = await client.get(
        f"/v1/workspaces/{member.workspace_id}/actions", headers=_auth_headers(member.session_id)
    )
    assert actions.status_code == 200
    action_list = actions.json()
    assert len(action_list) == 1
    assert action_list[0]["tool_name"] == "telegram.send_message"
    assert action_list[0]["status"] == "AWAITING_APPROVAL"


async def test_exhausting_every_tool_round_ends_as_an_explicit_incomplete_turn_not_a_silent_success(
    client: AsyncClient, db_available: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-CONV-008: hitting ai_max_tool_rounds without ever producing a
    final text answer must be surfaced as incomplete, never presented as
    if the model actually finished."""
    gateway = _ScriptedGateway(
        [
            [
                ToolCallReady(
                    call=ToolCallRequest(call_id="cN", name="list_my_open_tasks", arguments_json="{}")
                ),
                Completed(usage=GatewayUsage(input_tokens=1, output_tokens=1), finish_reason="tool_calls"),
            ]
        ]
    )
    monkeypatch.setattr(
        "doda.application.conversation_service.get_gateway", lambda provider, settings: gateway
    )

    member = await seed_workspace_member()
    create = await client.post(
        f"/v1/workspaces/{member.workspace_id}/conversations",
        json={},
        headers=_auth_headers(member.session_id),
    )
    conversation_id = create.json()["id"]

    post = await _post_message(
        client,
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(member.session_id),
        content="doim vosita chaqir",
    )
    assert post.status_code == 200
    events = _parse_sse(post.text)
    final_message = events[-1][1]["message"]
    assert final_message["finish_reason"] == "length"
    assert "Juda ko'p vosita chaqiruvidan" in final_message["content"]


async def test_a_customer_owner_disabled_provider_is_refused_before_any_byte_is_streamed(
    client: AsyncClient, db_available: bool
) -> None:
    """ai_provider_settings_service.assert_provider_enabled, wired into
    stream_message right after provider resolution: disabling a provider
    must actually stop a chat turn from using it — clearly, as a normal
    4xx before any SSE byte (the resolution chain already picked this
    provider, so the failure happens during `stream_message`'s FIRST
    yielded item, the exact "pre-stream" case `post_conversation_message`
    documents), never silently falling back to a different provider."""
    member = await seed_workspace_member()
    async with tenant_scoped_session(member.customer_id) as db:
        await ai_provider_settings_service.set_provider_enabled_for_customer(
            db, customer_id=member.customer_id, provider=Provider.OPENAI, enabled=False
        )
        await db.commit()

    create = await client.post(
        f"/v1/workspaces/{member.workspace_id}/conversations",
        json={},
        headers=_auth_headers(member.session_id),
    )
    conversation_id = create.json()["id"]

    post = await _post_message(
        client,
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(member.session_id),
        content="salom",
    )
    assert post.status_code == 403
    assert post.json()["code"] == "AI_PROVIDER_DISABLED"


class _AlwaysFailsTransiently:
    """A round-0 gateway call that always times out before yielding
    anything — the exact shape `stream_message`'s fallback branch is
    restricted to."""

    def __init__(self) -> None:
        self.calls = 0

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
        del model, mode, instructions, history, tools, max_output_tokens, response_schema
        self.calls += 1
        if False:
            yield  # pragma: no cover — makes this a real async generator function
        raise ModelTimeoutError("primary provider timed out")


class _AlwaysSucceeds:
    def __init__(self) -> None:
        self.calls = 0

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
        del model, mode, instructions, history, tools, max_output_tokens, response_schema
        self.calls += 1
        yield TextDelta(text="fallback provayderining javobi")
        yield Completed(usage=GatewayUsage(input_tokens=1, output_tokens=1), finish_reason="stop")


async def test_fallback_disabled_by_default_a_transient_round_0_failure_is_not_retried(
    client: AsyncClient, db_available: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _AlwaysFailsTransiently()
    fallback = _AlwaysSucceeds()
    monkeypatch.setattr(
        "doda.application.conversation_service.get_gateway",
        lambda provider, settings: primary if provider is Provider.OPENAI else fallback,
    )
    monkeypatch.setattr(
        "doda.application.ai_provider_settings_service.is_provider_configured",
        lambda provider, settings: True,
    )

    member = await seed_workspace_member()
    create = await client.post(
        f"/v1/workspaces/{member.workspace_id}/conversations",
        json={},
        headers=_auth_headers(member.session_id),
    )
    conversation_id = create.json()["id"]

    post = await _post_message(
        client,
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(member.session_id),
        content="salom",
    )
    # Fallback is opt-in, default OFF (CustomerAIFallbackSetting: row
    # absence means disabled) — nothing here ever turned it on, so the
    # transient failure must surface as a normal error, never silently
    # retried on a different provider.
    assert post.status_code == 504
    assert post.json()["code"] == "AI_PROVIDER_TIMEOUT"
    assert primary.calls == 1
    assert fallback.calls == 0


async def test_fallback_enabled_a_transient_round_0_failure_silently_completes_on_the_fallback_provider(
    client: AsyncClient, db_available: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _AlwaysFailsTransiently()
    fallback = _AlwaysSucceeds()
    monkeypatch.setattr(
        "doda.application.conversation_service.get_gateway",
        lambda provider, settings: primary if provider is Provider.OPENAI else fallback,
    )
    monkeypatch.setattr(
        "doda.application.ai_provider_settings_service.is_provider_configured",
        lambda provider, settings: True,
    )

    member = await seed_workspace_member()
    async with tenant_scoped_session(member.customer_id) as db:
        await ai_provider_settings_service.set_fallback_enabled_for_customer(
            db, customer_id=member.customer_id, enabled=True
        )
        await db.commit()

    create = await client.post(
        f"/v1/workspaces/{member.workspace_id}/conversations",
        json={},
        headers=_auth_headers(member.session_id),
    )
    conversation_id = create.json()["id"]

    post = await _post_message(
        client,
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(member.session_id),
        content="salom",
    )
    assert post.status_code == 200
    events = _parse_sse(post.text)
    assert events[-1][0] == "done"
    final_message = events[-1][1]["message"]
    assert final_message["content"] == "fallback provayderining javobi"
    # The fallback is never conflated with a manual switch: the
    # conversation's OWN pinned_provider stays untouched — only this
    # turn silently ran on the substitute.
    assert final_message["provider"] == "CLAUDE"
    assert primary.calls == 1
    assert fallback.calls == 1

    unaffected = await client.get(
        f"/v1/workspaces/{member.workspace_id}/conversations", headers=_auth_headers(member.session_id)
    )
    assert unaffected.json()[0]["pinned_provider"] is None


class _RecordingGateway:
    """Records the `history` it was actually called with — lets a test
    assert on exactly what got replayed to a DIFFERENT provider after a
    mid-conversation switch, not just that the turn succeeded."""

    def __init__(self, *, reply_text: str) -> None:
        self.reply_text = reply_text
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
        yield TextDelta(text=self.reply_text)
        yield Completed(usage=GatewayUsage(input_tokens=1, output_tokens=1), finish_reason="stop")


async def test_switching_mid_conversation_replays_prior_tool_call_history_to_the_new_provider(
    client: AsyncClient, db_available: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The explicit instruction: switching provider mid-conversation must
    preserve DODA-owned history while never forwarding a provider-
    specific call id AS IF it were the new provider's own — each
    adapter re-derives its native shape from the stored, provider-
    neutral ChatTurn/ToolCallRequest columns on every replay."""
    gateway_a = _RecordingGateway(reply_text="(unused — round 1 calls a tool instead)")
    gateway_b = _RecordingGateway(reply_text="ikkinchi provayderdan javob")

    # Round 1 (provider A / OPENAI, the system default) calls a tool —
    # override stream_chat just for that one call via a tiny wrapper so
    # THIS gateway's first call returns a tool call, not gateway_a's
    # generic reply.
    async def _first_call_is_a_tool_call(**kwargs: typing.Any) -> typing.AsyncIterator[GatewayEvent]:
        del kwargs
        yield ToolCallReady(
            call=ToolCallRequest(call_id="a-call-1", name="list_my_open_tasks", arguments_json="{}")
        )
        yield Completed(usage=GatewayUsage(input_tokens=1, output_tokens=1), finish_reason="tool_calls")

    gateway_a.stream_chat = _first_call_is_a_tool_call  # type: ignore[method-assign]

    monkeypatch.setattr(
        "doda.application.conversation_service.get_gateway",
        lambda provider, settings: gateway_a if provider is Provider.OPENAI else gateway_b,
    )

    member = await seed_workspace_member()
    create = await client.post(
        f"/v1/workspaces/{member.workspace_id}/conversations",
        json={},
        headers=_auth_headers(member.session_id),
    )
    conversation_id = create.json()["id"]

    first = await _post_message(
        client,
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(member.session_id),
        content="ishlarimni ko'rsat",
    )
    assert first.status_code == 200
    # Round 2 (still provider A, same turn) answers with plain text via
    # gateway_a's normal stream_chat (restored implicitly since only the
    # FIRST call was overridden — but the override replaced the bound
    # method entirely, so round 2 within the SAME turn would also hit
    # the tool-call stub again). To keep this test's one concern clean
    # (switch + history replay across TURNS, not within one), the first
    # turn is allowed to end as an incomplete tool-call round; what
    # matters is the stored history it leaves behind.
    listed = await client.get(
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(member.session_id),
    )
    roles_after_turn_one = [m["role"] for m in listed.json()]
    assert "TOOL" in roles_after_turn_one  # the read tool's result is real, stored history

    switch = await client.post(
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/provider",
        json={"provider": "CLAUDE", "model": "claude-sonnet-5"},
        headers=_auth_headers(member.session_id),
    )
    assert switch.status_code == 200

    second = await _post_message(
        client,
        f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
        headers=_auth_headers(member.session_id),
        content="davom ettiring",
    )
    assert second.status_code == 200
    events = _parse_sse(second.text)
    assert events[-1][1]["message"]["content"] == "ikkinchi provayderdan javob"
    assert events[-1][1]["message"]["provider"] == "CLAUDE"

    # gateway_b (the NEW provider) received the FULL prior history,
    # reconstructed from storage — including the tool-call turn and its
    # result that provider A originally produced — never a blank slate
    # and never a gap.
    assert len(gateway_b.received_histories) == 1
    replayed = gateway_b.received_histories[0]
    assert any(t.tool_calls and t.tool_calls[0].name == "list_my_open_tasks" for t in replayed)
    assert any(t.role is ChatRole.TOOL for t in replayed)
    assert replayed[-1].content == "davom ettiring"
