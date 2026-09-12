"""Telegram connector against live Postgres + Redis — proves the real
outbox -> Redis Stream -> consumer -> Action state-transition pipeline
end to end. Everything internal to this codebase here is real (real
Postgres, real Redis, the real outbox_relay publisher, the real
apply_transition chokepoint); only the external HTTP call to Telegram's
own API is a test double (httpx.MockTransport), because no real bot
token or chat is available in this environment. See
infrastructure/telegram_relay.py's own docstring for the honest scope
of what that does and doesn't prove, and test_telegram_client.py for
the client's own request/response handling in isolation.
"""

import asyncio
import os
import signal
import uuid

import httpx
import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from doda.application.action_service import (
    consume_approval,
    propose_action,
    request_approval,
    validate_action,
)
from doda.config import get_settings
from doda.db import tenant_scoped_session
from doda.domain.action.models import Action, ActionStatus, RiskLevel
from doda.infrastructure.outbox_relay import relay_once as outbox_relay_once
from doda.infrastructure.telegram_relay import (
    CONSUMER_GROUP,
    STREAM_NAME,
    main,
    process_entry,
    relay_once,
    run_forever,
)
from tests.integration.conftest import assert_worker_still_running_before_signaling


@pytest.fixture
async def redis_client():
    # No decode_responses=True: telegram_relay.main() creates its client
    # the same way outbox_relay.main() does, so fields arrive as bytes in
    # production — matching that here is what makes this test meaningful.
    client = Redis.from_url(get_settings().redis_url.get_secret_value())
    try:
        await client.ping()
    except RedisConnectionError:
        pytest.skip("Redis not reachable — start it with `docker compose up -d redis`")
    yield client
    await client.aclose()


async def _seed_ready_telegram_action(
    *, chat_id: str = "555", text: str = "hello"
) -> tuple[uuid.UUID, uuid.UUID]:
    """Propose+validate+approve a telegram.send_message action all the way
    to READY (it's raised to R3 by tool_policy, so this exercises the real
    approval path, not just an auto-approved R0-R2 action). Returns
    (customer_id, action_id)."""
    customer_id = uuid.uuid4()
    workspace_id, trace_id = uuid.uuid4(), uuid.uuid4()

    async with tenant_scoped_session(customer_id) as session:
        action, _ = await propose_action(
            session,
            customer_id=customer_id,
            workspace_id=workspace_id,
            trace_id=trace_id,
            actor_id="user:alice",
            tool_name="telegram.send_message",
            risk_level=RiskLevel.R0,  # raised to R3 by tool_policy
            payload={"chat_id": chat_id, "text": text},
            idempotency_key=f"idem-telegram-relay-{uuid.uuid4()}",
        )
        await validate_action(session, action, actor_id="user:alice")
        assert action.status is ActionStatus.AWAITING_APPROVAL
        approval = await request_approval(session, action)
        await consume_approval(session, action, approval, approver_id="user:approver", nonce=approval.nonce)
        assert action.status is ActionStatus.READY
        action_id = action.id

    return customer_id, action_id


def _mock_http_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _get_action(customer_id: uuid.UUID, action_id: uuid.UUID) -> Action:
    async with tenant_scoped_session(customer_id) as session:
        action = await session.get(Action, action_id)
        assert action is not None
        return action


async def _drain_until_resolved(
    redis: Redis,
    http_client: httpx.AsyncClient,
    *,
    bot_token: str | None,
    customer_id: uuid.UUID,
    action_id: uuid.UUID,
    max_batches: int = 200,
) -> Action:
    """This Redis instance is shared across this whole (long-running) test
    session, so `doda:outbox:action.ready.v1` can carry a large backlog of
    older entries from earlier tests -- `relay_once`'s own batch size means
    a single call may only reach entries far older than the one this test
    just seeded. Keep draining batches (real production behavior: the
    worker loop just keeps polling) until OUR action resolves, rather than
    assuming one `relay_once` call is enough."""
    for _ in range(max_batches):
        processed = await relay_once(redis, http_client, bot_token=bot_token)
        action = await _get_action(customer_id, action_id)
        if action.status is not ActionStatus.READY:
            return action
        if processed == 0:
            break
    pytest.fail(f"action {action_id} never left READY after draining the backlog")


async def test_ready_telegram_action_is_driven_to_succeeded(db_available: bool, redis_client: Redis) -> None:
    customer_id, action_id = await _seed_ready_telegram_action()
    published = await outbox_relay_once(redis_client)
    assert published >= 1

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    async with _mock_http_client(handler) as http_client:
        action = await _drain_until_resolved(
            redis_client,
            http_client,
            bot_token="fake-test-token",
            customer_id=customer_id,
            action_id=action_id,
        )
    assert action.status is ActionStatus.SUCCEEDED


async def test_telegram_api_failure_drives_action_to_failed(db_available: bool, redis_client: Redis) -> None:
    customer_id, action_id = await _seed_ready_telegram_action()
    await outbox_relay_once(redis_client)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "chat not found"})

    async with _mock_http_client(handler) as http_client:
        action = await _drain_until_resolved(
            redis_client,
            http_client,
            bot_token="fake-test-token",
            customer_id=customer_id,
            action_id=action_id,
        )
    assert action.status is ActionStatus.FAILED


async def test_missing_bot_token_drives_action_to_failed_without_calling_telegram(
    db_available: bool, redis_client: Redis
) -> None:
    customer_id, action_id = await _seed_ready_telegram_action()
    await outbox_relay_once(redis_client)

    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    async with _mock_http_client(handler) as http_client:
        action = await _drain_until_resolved(
            redis_client, http_client, bot_token=None, customer_id=customer_id, action_id=action_id
        )

    assert called is False
    assert action.status is ActionStatus.FAILED


async def test_a_non_telegram_action_is_left_alone(db_available: bool, redis_client: Redis) -> None:
    """The connector must only act on telegram.send_message — every other
    tool_name's READY action is real production traffic this connector
    has no business touching."""
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        action, _ = await propose_action(
            session,
            customer_id=customer_id,
            workspace_id=uuid.uuid4(),
            trace_id=uuid.uuid4(),
            actor_id="user:alice",
            tool_name="knowledge.read",
            risk_level=RiskLevel.R1,
            payload={"query": "q"},
            idempotency_key=f"idem-other-tool-{uuid.uuid4()}",
        )
        await validate_action(session, action, actor_id="user:alice")
        assert action.status is ActionStatus.READY
        action_id = action.id

    await outbox_relay_once(redis_client)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must never call Telegram for a non-telegram action")

    async with _mock_http_client(handler) as http_client:
        await relay_once(redis_client, http_client, bot_token="fake-test-token")

    action = await _get_action(customer_id, action_id)
    assert action.status is ActionStatus.READY  # untouched


async def test_redelivery_of_an_already_succeeded_action_does_not_resend(db_available: bool) -> None:
    """Idempotency guard: a stream entry can be redelivered (consumer crash
    before XACK). Once an action is past READY, a second delivery for the
    same entry must not call Telegram again — proven by calling
    process_entry directly a second time (bypassing stream/XACK mechanics,
    which is exactly the scenario a redelivery reproduces: the same
    (customer_id, aggregate_id) fields processed twice).

    Audit-zanjiri-style verification of this test's own meaningfulness:
    temporarily removing telegram_relay._drive_to_running's explicit
    status check did NOT make this test pass with a double call (which
    would have meant the test was vacuous) — it instead surfaced a real
    doda.domain.action.state_machine.InvalidActionTransition
    (SUCCEEDED -> RUNNING) from apply_transition's own, independent
    state-machine guard. That confirms two things: the explicit check is
    real (its removal changes behavior, from a clean skip to an
    exception), and the deeper apply_transition layer is a genuine
    backstop against the case this test cares about most (Telegram never
    gets called twice), not just an assumed one. See
    infrastructure/telegram_relay.py's module docstring for the full
    two-layer explanation."""
    customer_id, action_id = await _seed_ready_telegram_action()

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    fields = {b"customer_id": str(customer_id).encode(), b"aggregate_id": str(action_id).encode()}

    async with _mock_http_client(handler) as http_client:
        await process_entry(http_client, fields=fields, bot_token="fake-test-token")
        assert call_count == 1
        action = await _get_action(customer_id, action_id)
        assert action.status is ActionStatus.SUCCEEDED

        # Redelivery of the exact same entry.
        await process_entry(http_client, fields=fields, bot_token="fake-test-token")

    assert call_count == 1  # Telegram was NOT called again
    action = await _get_action(customer_id, action_id)
    assert action.status is ActionStatus.SUCCEEDED  # unchanged


async def test_malformed_payload_drives_action_to_failed_without_calling_telegram(
    db_available: bool, redis_client: Redis
) -> None:
    """A telegram.send_message action whose payload doesn't carry a string
    chat_id/text is a real possibility: `propose_action` takes an arbitrary
    payload dict and nothing validates its shape per tool (FR-ACT-001's
    full tool registry, with per-tool payload schemas, is deliberately not
    built — see domain/action/tool_policy.py). The connector must fail such
    an action explicitly rather than crash or send something malformed.
    """
    customer_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    async with tenant_scoped_session(customer_id) as session:
        action, _ = await propose_action(
            session,
            customer_id=customer_id,
            workspace_id=workspace_id,
            trace_id=uuid.uuid4(),
            actor_id="user:alice",
            tool_name="telegram.send_message",
            risk_level=RiskLevel.R0,  # raised to R3 by tool_policy
            payload={"recipient": "not-a-chat-id"},  # no chat_id/text at all
            idempotency_key=f"idem-telegram-malformed-{uuid.uuid4()}",
        )
        await validate_action(session, action, actor_id="user:alice")
        approval = await request_approval(session, action)
        await consume_approval(session, action, approval, approver_id="user:approver", nonce=approval.nonce)
        action_id = action.id

    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    fields = {b"customer_id": str(customer_id).encode(), b"aggregate_id": str(action_id).encode()}
    async with _mock_http_client(handler) as http_client:
        await process_entry(http_client, fields=fields, bot_token="fake-test-token")

    assert called is False  # never attempted a send with a malformed payload
    action = await _get_action(customer_id, action_id)
    assert action.status is ActionStatus.FAILED


async def test_an_unprocessable_entry_is_left_unacked_in_the_pending_list(
    db_available: bool, redis_client: Redis
) -> None:
    """relay_once's own comment claims an entry that raises is "left
    un-ACK'd — stays in the PEL for reconciliation, not silently dropped".
    That claim had never been verified. Inject a structurally broken entry
    (no customer_id/aggregate_id fields at all, which is what a publisher
    bug or a hand-written XADD would look like) and assert both halves:
    relay_once survives it, and Redis still lists it as pending.
    """
    entry_id = await redis_client.xadd(STREAM_NAME, {"unexpected": "shape"})

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must never reach Telegram for an unprocessable entry")

    async with _mock_http_client(handler) as http_client:
        # Does not raise, even though process_entry itself will KeyError.
        await relay_once(redis_client, http_client, bot_token="fake-test-token")

    try:
        pending = await redis_client.xpending_range(
            STREAM_NAME, CONSUMER_GROUP, min=entry_id, max=entry_id, count=10
        )
        assert len(pending) == 1, "a failed entry must stay in the PEL, not be silently ACK'd"
    finally:
        # Remove the probe entry from the STREAM, not just the group's PEL:
        # this is a real shared Redis stream that other tests read in full
        # (test_outbox_relay.py iterates every entry and indexes
        # fields["aggregate_id"]), so an XACK alone — which clears the PEL
        # but leaves the entry in the stream — makes this test poison its
        # siblings. Caught exactly that way: the full suite failed with a
        # KeyError in test_outbox_relay while this file alone passed. Same
        # lesson as the E2E specs' separate seeds: never leave shared
        # mutable state behind.
        await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, entry_id)
        await redis_client.xdel(STREAM_NAME, entry_id)


async def test_relay_once_returns_zero_when_nothing_new_is_pending(
    db_available: bool, redis_client: Redis
) -> None:
    """The idle path: with the stream drained, xreadgroup blocks briefly and
    then returns nothing, which relay_once reports as 0 processed rather
    than treating an empty read as an error."""
    async with _mock_http_client(
        lambda request: httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    ) as http_client:
        # Drain in a LOOP, not once: relay_once reads at most 50 entries per
        # call, and this stream carries whatever every other test in the run
        # published. A single drain call leaves the rest pending and the
        # assertion below then reads a backlog instead of an idle stream —
        # reproduced for real with a 60-entry backlog: `assert 10 == 0`.
        while await relay_once(redis_client, http_client, bot_token="fake-test-token"):
            pass
        assert await relay_once(redis_client, http_client, bot_token="fake-test-token") == 0


async def test_run_forever_drives_an_action_then_stops_promptly_on_stop_event(
    db_available: bool, redis_client: Redis
) -> None:
    """`run_forever` is the actual worker loop — the same gap outbox_relay.py
    had before its own run_forever test existed: every other test here calls
    `relay_once` directly, so the loop that a real deployment runs was never
    exercised. Proves it drives a real action to SUCCEEDED AND honors a
    shutdown signal (xreadgroup's own block bounds each iteration, so this
    must not wait on anything longer).
    """
    customer_id, action_id = await _seed_ready_telegram_action()
    await outbox_relay_once(redis_client)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    stop_event = asyncio.Event()
    async with _mock_http_client(handler) as http_client:
        task = asyncio.create_task(
            run_forever(redis_client, http_client, stop_event=stop_event, bot_token="fake-test-token")
        )
        try:
            for _ in range(100):
                action = await _get_action(customer_id, action_id)
                if action.status is not ActionStatus.READY:
                    break
                await asyncio.sleep(0.1)
            else:
                pytest.fail("run_forever never drove the action out of READY")
        finally:
            stop_event.set()
            # Generous vs. DEFAULT_BLOCK_MS (1s): the loop can only notice
            # the event between blocking reads. A regression that ignored
            # stop_event entirely would hang here instead.
            await asyncio.wait_for(task, timeout=10)

    assert action.status is ActionStatus.SUCCEEDED


async def test_main_stops_cleanly_on_sigterm(db_available: bool, redis_client: Redis) -> None:
    """The real worker entrypoint (`python -m doda.infrastructure.telegram_relay`):
    registers SIGTERM/SIGINT handlers, opens its own Redis + httpx clients,
    and exits on signal rather than needing a hard kill. Mirrors
    test_outbox_relay.py's identical test for the sibling worker."""
    task = asyncio.create_task(main())
    await asyncio.sleep(0.3)  # let it start and register the signal handlers
    assert_worker_still_running_before_signaling(task)
    os.kill(os.getpid(), signal.SIGTERM)
    await asyncio.wait_for(task, timeout=10)
