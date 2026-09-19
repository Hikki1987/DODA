"""NFR-PORT-001 — "Portativlik: provider-neutral domain va AI gateway,
verified via ikkinchi provider bilan smoke test."

ADR-009's own text claims this was already proven when Gemini/Claude were
added "with zero changes to `doda.ai.types`/`doda.ai.port`" — but that claim
was never actually smoke-tested end-to-end. `tests/unit/test_{openai,gemini,
claude}_gateway.py` each test one adapter in isolation (its own request/
response shape against a mocked transport); `tests/integration/
test_conversations_api.py`'s provider-switch test
(`test_switching_mid_conversation_replays_prior_tool_call_history_to_the_
new_provider`) swaps providers mid-conversation, but through a
`_RecordingGateway` test double, not the real adapters this codebase ships.
Nothing had ever driven the FULL orchestration
(`conversation_service.stream_message` — persistence, budget reserve/
reconcile, tool-round loop, SSE assembly, the entire authoritative-chain
HTTP path) against two (here: all three) of the real, concrete
`ModelGateway` implementations to prove the domain/application layer
needs zero special-casing per provider.

Each adapter's own real SDK client is used, with only its HTTP transport
swapped for a mock (the same technique as the three unit test files above)
— no real network call, no real API key, consistent with this
environment's network policy (ADR-008/ADR-009) and the "real integration
bajarilmagan bo'lsa PASS deb yozma" rule: this proves the ORCHESTRATION
layer's provider-neutrality, not that a live OpenAI/Gemini/Claude account
works (that is the eval harness's job, when a real key is present).
"""

import json

import httpx
import httpx2
import pytest
from httpx import ASGITransport, AsyncClient, Response

from doda.ai.types import Provider
from doda.infrastructure.claude_gateway import ClaudeGateway
from doda.infrastructure.gemini_gateway import GeminiGateway
from doda.infrastructure.openai_gateway import OpenAIGateway
from doda.main import app
from tests.integration.conftest import seed_workspace_member


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_headers(session_id) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


async def _post_message(client: AsyncClient, url: str, *, headers: dict[str, str], content: str) -> Response:
    async with client.stream(
        "POST", url, json={"content": content, "mode": "STANDARD"}, headers=headers
    ) as response:
        await response.aread()
        return response


def _sse_events(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip("\n").split("\n\n"):
        if not block:
            continue
        event_line, data_line = block.split("\n", 1)
        events.append((event_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: "))))
    return events


def _real_openai_gateway(reply: str) -> OpenAIGateway:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = "".join(
            f"data: {json.dumps(e)}\n\n"
            for e in [
                {"type": "response.output_text.delta", "delta": reply, "sequence_number": 1},
                {
                    "type": "response.completed",
                    "sequence_number": 2,
                    "response": {
                        "id": "resp_1",
                        "object": "response",
                        "created_at": 0,
                        "model": "gpt-5-mini",
                        "status": "completed",
                        "output": [],
                        "parallel_tool_calls": True,
                        "tool_choice": "auto",
                        "tools": [],
                        "usage": {
                            "input_tokens": 10,
                            "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                            "output_tokens": 5,
                            "output_tokens_details": {"reasoning_tokens": 0},
                            "total_tokens": 15,
                        },
                    },
                },
            ]
        ).encode()
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    gateway = OpenAIGateway(api_key="sk-fake-openai-key", timeout_seconds=5.0)
    gateway._client = gateway._client.with_options(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), max_retries=0
    )
    return gateway


def _real_gemini_gateway(reply: str) -> GeminiGateway:
    def handler(request: httpx.Request) -> httpx.Response:
        body = "".join(
            f"data: {json.dumps(e)}\n\n"
            for e in [
                {
                    "candidates": [
                        {
                            "content": {"role": "model", "parts": [{"text": reply}]},
                            "finishReason": "STOP",
                            "index": 0,
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 10,
                        "candidatesTokenCount": 5,
                        "totalTokenCount": 15,
                        "cachedContentTokenCount": 0,
                    },
                }
            ]
        ).encode()
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    return GeminiGateway(
        api_key="AIzaFakeGeminiKey",
        timeout_seconds=5.0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _real_claude_gateway(reply: str) -> ClaudeGateway:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = "".join(
            f"event: {e['type']}\ndata: {json.dumps(e)}\n\n"
            for e in [
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "model": "claude-sonnet-5",
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 10, "output_tokens": 0},
                    },
                },
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": reply},
                },
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 5},
                },
                {"type": "message_stop"},
            ]
        ).encode()
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    gateway = ClaudeGateway(api_key="sk-ant-fake-claude-key", timeout_seconds=5.0)
    gateway._client = gateway._client.with_options(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), max_retries=0
    )
    return gateway


async def test_the_full_chat_orchestration_runs_unchanged_against_every_real_provider_adapter(
    client: AsyncClient, db_available: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The smoke test itself: one conversation per provider, each pinned to
    a DIFFERENT real gateway implementation, driven through the exact same
    HTTP endpoint/authz chain/persistence/budget code. If any of this needed
    provider-specific branching, at least one of the three would fail or
    require a different call shape here — none does."""
    gateways = {
        Provider.OPENAI: _real_openai_gateway("Salom OpenAI'dan"),
        Provider.GEMINI: _real_gemini_gateway("Salom Gemini'dan"),
        Provider.CLAUDE: _real_claude_gateway("Salom Claude'dan"),
    }
    monkeypatch.setattr(
        "doda.application.conversation_service.get_gateway", lambda provider, settings: gateways[provider]
    )

    member = await seed_workspace_member()
    expectations = [
        (Provider.OPENAI, "gpt-5-mini", "Salom OpenAI'dan"),
        (Provider.GEMINI, "gemini-3.1-flash-lite", "Salom Gemini'dan"),
        (Provider.CLAUDE, "claude-sonnet-5", "Salom Claude'dan"),
    ]

    for provider, model, expected_reply in expectations:
        create = await client.post(
            f"/v1/workspaces/{member.workspace_id}/conversations",
            json={},
            headers=_auth_headers(member.session_id),
        )
        assert create.status_code == 200
        conversation_id = create.json()["id"]

        switch = await client.post(
            f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/provider",
            json={"provider": provider.value, "model": model},
            headers=_auth_headers(member.session_id),
        )
        assert switch.status_code == 200

        posted = await _post_message(
            client,
            f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
            headers=_auth_headers(member.session_id),
            content="Salom!",
        )
        assert posted.status_code == 200, (provider, posted.text)
        events = _sse_events(posted.text)
        final_message = events[-1][1]["message"]
        assert final_message["content"] == expected_reply
        assert final_message["provider"] == provider.value
        assert final_message["model"] == model

        listed = await client.get(
            f"/v1/workspaces/{member.workspace_id}/conversations/{conversation_id}/messages",
            headers=_auth_headers(member.session_id),
        )
        assert listed.status_code == 200
        assert [m["role"] for m in listed.json()] == ["USER", "ASSISTANT"]
