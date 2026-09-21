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
import json
import os
import signal
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select

from doda.application.action_service import (
    consume_approval,
    propose_action,
    request_approval,
    validate_action,
)
from doda.config import get_settings
from doda.db import async_session_factory, tenant_scoped_session
from doda.domain.action.models import Action, ActionStatus, RiskLevel
from doda.domain.audit.models import AuditEvent
from doda.domain.outbox.models import OutboxMessage
from doda.infrastructure import telegram_relay as telegram_relay_module
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


async def _get_succeeded_audit_event(customer_id: uuid.UUID) -> AuditEvent:
    # customer_id is a fresh uuid4 per seeded test (see
    # _seed_ready_telegram_action), and tenant_scoped_session's RLS scopes
    # this query to it — exactly one action, exactly one SUCCEEDED event.
    async with tenant_scoped_session(customer_id) as session:
        return (
            await session.execute(select(AuditEvent).where(AuditEvent.event_type == "action.succeeded.v1"))
        ).scalar_one()


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

    # FR-ACT-007: the SUCCEEDED transition must carry Telegram's own
    # message_id as its receipt, not just "no exception was raised".
    event = await _get_succeeded_audit_event(customer_id)
    assert event.safe_metadata["provider_receipt"] == {"message_id": 1}


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


async def test_two_concurrent_telegram_relay_workers_never_double_send_the_same_action(
    db_available: bool, redis_client: Redis
) -> None:
    """NFR-SCL-001's own verification method ('Ikki instansda test') was
    already applied to outbox_relay.py's Postgres-side locking
    (test_outbox_relay.py's own concurrency test), but never to THIS
    connector's Redis consumer-group side — the one that actually matters
    for FR-ACT-004/9.2 here, since a double Telegram send is a real,
    irreversible external side effect, not just a duplicate DB row.
    test_redelivery_of_an_already_succeeded_action_does_not_resend above
    only proves the SEQUENTIAL case (one worker, redelivered after the
    fact) — this proves two workers reading the SAME consumer group at
    the SAME time (a real asyncio.gather, not sequential awaits) never
    both get handed the same stream entry, even though both use the
    exact same hardcoded CONSUMER_NAME production runs with today (see
    the module's own CONSUMER_NAME constant) — it's Redis's own atomic,
    single-threaded command execution doing the work here, not any
    locking this codebase itself implements (unlike outbox_relay's
    FOR UPDATE SKIP LOCKED, which needed its own proof for exactly that
    reason).
    """

    def _drain_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 0}})

    # Same backlog concern test_outbox_relay.py's own concurrency test
    # documents: this Redis instance is shared across the whole test
    # session, so leftover PEL entries from earlier tests could otherwise
    # occupy a batch slot ahead of the five this test seeds below.
    async with _mock_http_client(_drain_handler) as drain_client:
        while await relay_once(redis_client, drain_client, bot_token="fake-test-token"):
            pass

    seeded = [
        await _seed_ready_telegram_action(chat_id=f"concurrent-drill-{i}", text=f"msg {i}") for i in range(5)
    ]
    while await outbox_relay_once(redis_client):
        pass

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["chat_id"])
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(calls)}})

    async with _mock_http_client(handler) as http_client:
        for _ in range(20):
            statuses = [(await _get_action(cid, aid)).status for cid, aid in seeded]
            if all(status is not ActionStatus.READY for status in statuses):
                break
            await asyncio.gather(
                relay_once(redis_client, http_client, bot_token="fake-test-token"),
                relay_once(redis_client, http_client, bot_token="fake-test-token"),
            )
        else:
            pytest.fail("not every seeded action left READY")

    expected_chat_ids = [f"concurrent-drill-{i}" for i in range(5)]
    # Exactly once each — never twice (a double send), never zero (dropped).
    assert sorted(calls) == sorted(expected_chat_ids)

    for customer_id, action_id in seeded:
        action = await _get_action(customer_id, action_id)
        assert action.status is ActionStatus.SUCCEEDED


async def _publish_pending_row_without_committing(redis: Redis, action_id: uuid.UUID) -> None:
    """Simulates outbox_relay.relay_once's own documented crash window: it
    XADDs to Redis for real, then updates published_at — but *inside* a
    single Postgres transaction, so a crash between the two leaves
    published_at unset and the same row eligible for a real, second publish.
    No explicit session.begin()/commit() here at all — closing the session
    without ever committing is exactly the FR-AUTH-006 lesson from this
    codebase's own history (an uncommitted transaction is silently
    discarded on scope exit), which is what makes this a faithful crash
    simulation rather than a rollback dressed up as one."""
    async with async_session_factory() as session:
        message = (
            await session.execute(
                select(OutboxMessage)
                .where(OutboxMessage.aggregate_id == action_id)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one()
        await redis.xadd(
            f"doda:outbox:{message.event_type}",
            {
                "id": str(message.id),
                "customer_id": str(message.customer_id),
                "aggregate_type": message.aggregate_type,
                "aggregate_id": str(message.aggregate_id),
                "payload": json.dumps(message.payload),
            },
        )
        message.published_at = datetime.now(UTC)
        message.attempts += 1
        # No commit — the crash.


async def test_a_crash_between_outbox_publish_and_commit_still_ends_in_exactly_one_send(
    db_available: bool, redis_client: Redis
) -> None:
    """FR-ACT-008's own acceptance criterion: 'Crash-recovery testida
    yo'qolgan yoki ikkilangan effekt yo'q' (no lost or duplicated effect in
    a crash-recovery test). Every existing redelivery/concurrency test in
    this file and test_outbox_relay.py proves ONE of two separate legs —
    either that two concurrent relay_once calls never double-publish the
    SAME row, or that redelivering the SAME Redis stream entry never
    double-sends. Neither reproduces outbox_relay.py's own documented
    crash window (XADD succeeds, then the process dies before its Postgres
    commit persists published_at) — which is a *third*, distinct way a
    duplicate can arise: the SAME outbox row, republished as a genuinely
    SECOND, distinct Redis Stream entry, because the first publish was
    never durably recorded.

    Simulated here by publishing once without committing (the crash),
    then letting the real relay_once publish the same still-pending row a
    second time for real. This must produce two distinct stream entries
    for the one action — proving the duplication is real, not assumed —
    and the connector's own existing idempotency (already proven against
    Redis-level redelivery of a single entry, see
    test_redelivery_of_an_already_succeeded_action_does_not_resend) must
    still collapse that onto exactly one Telegram send.
    """
    customer_id, action_id = await _seed_ready_telegram_action(chat_id="crash-drill")

    await _publish_pending_row_without_committing(redis_client, action_id)
    published = await outbox_relay_once(redis_client)
    assert published >= 1  # the real relay saw the row as still-pending and republished it

    stream = "doda:outbox:action.ready.v1"
    entries = await redis_client.xrange(stream)
    matching = [
        fields for _entry_id, fields in entries if fields.get(b"aggregate_id") == str(action_id).encode()
    ]
    assert len(matching) == 2  # the crash really did produce a second, distinct entry

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
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
    assert call_count == 1  # duplicated outbox entry, but exactly one external effect


async def test_a_transient_failure_that_clears_up_still_succeeds(
    db_available: bool, redis_client: Redis
) -> None:
    """FR-ACT-005 (Must): "Provider outage simulyatsiyasida ma'lumot
    yo'qolmaydi" — a short-lived outage (first two attempts can't even
    reach Telegram, the third succeeds) must not lose the action to a
    terminal FAILED; it must retry and land on SUCCEEDED, same as if
    there had been no outage at all. Uses a connection failure, not a
    5xx/timeout — see telegram_client.TelegramTransientError's own
    docstring (UC-004's mandated "provider timeout bergan lekin xat
    aslida yuborilgan" scenario) for why only a failure KNOWN to have
    happened before Telegram could have queued anything is retried."""
    customer_id, action_id = await _seed_ready_telegram_action()

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})

    fields = {b"customer_id": str(customer_id).encode(), b"aggregate_id": str(action_id).encode()}
    async with _mock_http_client(handler) as http_client:
        await process_entry(http_client, fields=fields, bot_token="fake-test-token")

    assert call_count == 3  # two failed attempts, then the retry that succeeded
    action = await _get_action(customer_id, action_id)
    assert action.status is ActionStatus.SUCCEEDED


async def test_a_sustained_transient_outage_still_ends_in_a_bounded_failed(
    db_available: bool, redis_client: Redis
) -> None:
    """The other half of the same fix: retries are bounded
    (TELEGRAM_SEND_ATTEMPTS), not infinite — an outage that never clears
    up within that budget still ends in a terminal FAILED, exactly as
    before this fix, rather than hammering Telegram forever."""
    customer_id, action_id = await _seed_ready_telegram_action()

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("connection refused")

    fields = {b"customer_id": str(customer_id).encode(), b"aggregate_id": str(action_id).encode()}
    async with _mock_http_client(handler) as http_client:
        await process_entry(http_client, fields=fields, bot_token="fake-test-token")

    assert call_count == 3  # TELEGRAM_SEND_ATTEMPTS, not unbounded
    action = await _get_action(customer_id, action_id)
    assert action.status is ActionStatus.FAILED


async def test_a_read_timeout_is_not_retried_even_once(db_available: bool, redis_client: Redis) -> None:
    """UC-004's own mandated negative scenario, exercised at the relay
    level (telegram_client's own unit test covers the client itself):
    'provider timeout bergan lekin xat aslida yuborilgan'. A read timeout
    must NOT be retried — Telegram may already have sent the message, so
    a second attempt risks a real duplicate. Exactly one call, straight
    to terminal FAILED."""
    customer_id, action_id = await _seed_ready_telegram_action()

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("timed out waiting for a response")

    fields = {b"customer_id": str(customer_id).encode(), b"aggregate_id": str(action_id).encode()}
    async with _mock_http_client(handler) as http_client:
        await process_entry(http_client, fields=fields, bot_token="fake-test-token")

    assert call_count == 1  # not retried — the send may have already gone through
    action = await _get_action(customer_id, action_id)
    assert action.status is ActionStatus.FAILED


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


async def test_main_starts_and_warns_when_no_bot_token_is_configured(
    db_available: bool, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """main()'s own "no bot token" branch has never run in this session:
    a real Telegram bot token has been in backend/.env since OD-002, so
    every prior test_main_stops_cleanly_on_sigterm run took the OTHER
    branch of `if settings.telegram_bot_token is None:`. This proves the
    entrypoint itself degrades gracefully on a real misconfiguration
    (warns, keeps polling, never crashes at startup) rather than assuming
    it — any backlog telegram action it picks up during the run still
    resolves to FAILED via the already-proven bot_token=None path (see
    test_missing_bot_token_drives_action_to_failed_without_calling_
    telegram), it just never gets there through a crashed process."""
    unconfigured = get_settings().model_copy(update={"telegram_bot_token": None})
    monkeypatch.setattr(telegram_relay_module, "get_settings", lambda: unconfigured)

    task = asyncio.create_task(main())
    await asyncio.sleep(0.3)
    assert_worker_still_running_before_signaling(task)
    os.kill(os.getpid(), signal.SIGTERM)
    await asyncio.wait_for(task, timeout=10)
