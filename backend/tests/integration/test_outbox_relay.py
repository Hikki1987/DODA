"""Outbox relay against live Postgres + Redis — proves the outbox -> Redis
Stream leg of ADR-003 actually delivers, not just that rows get marked.

Uses its own tenant_scoped_session directly (rather than the shared
tenant_session fixture) so the propose/validate transaction is fully
committed before relay_once opens its own connection to read it — two
separate connections under READ COMMITTED won't see each other's
uncommitted writes, matching how the real app and a background relay
worker are two separate processes in production.
"""

import asyncio
import json
import os
import signal
import uuid

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from doda.application.action_service import propose_action, validate_action
from doda.config import get_settings
from doda.db import tenant_scoped_session
from doda.domain.action.models import RiskLevel
from doda.infrastructure.outbox_relay import main, relay_once, run_forever
from tests.integration.conftest import assert_worker_still_running_before_signaling


@pytest.fixture
async def redis_client():
    client = Redis.from_url(get_settings().redis_url.get_secret_value(), decode_responses=True)
    try:
        await client.ping()
    except RedisConnectionError:
        pytest.skip("Redis not reachable — start it with `docker compose up -d redis`")
    yield client
    await client.aclose()


async def _relay_until_drained(redis_client: Redis, *, batch_size: int = 100) -> int:
    """Relay every pending outbox row, not just one batch, and return how many
    were published.

    `relay_once` reads a bounded batch of the outbox PLATFORM-WIDE —
    outbox_messages is deliberately RLS-exempt so one relay can serve every
    tenant (ADR-003) — so the rows it picks up include whatever any other test
    in the run left pending. A single call therefore proves nothing about this
    test's own row once the backlog is larger than a batch. Reproduced for
    real by seeding a 120-row backlog: the very first test in this file failed
    because its own action was still queued behind that backlog.
    """
    published = 0
    while batch := await relay_once(redis_client, batch_size=batch_size):
        published += batch
    return published


async def test_relay_publishes_ready_action_to_its_event_stream(
    db_available: bool, redis_client: Redis
) -> None:
    customer_id = uuid.uuid4()
    workspace_id, trace_id = uuid.uuid4(), uuid.uuid4()

    async with tenant_scoped_session(customer_id) as session:
        action, _ = await propose_action(
            session,
            customer_id=customer_id,
            workspace_id=workspace_id,
            trace_id=trace_id,
            actor_id="user:alice",
            tool_name="knowledge.read",
            risk_level=RiskLevel.R1,
            payload={"query": "quarterly report"},
            idempotency_key="idem-relay-test",
        )
        await validate_action(session, action, actor_id="user:alice")

    published_count = await _relay_until_drained(redis_client)
    assert published_count >= 1

    stream = "doda:outbox:action.ready.v1"
    entries = await redis_client.xrange(stream)
    matching = [fields for _entry_id, fields in entries if fields.get("aggregate_id") == str(action.id)]

    assert len(matching) == 1
    assert matching[0]["aggregate_type"] == "action"
    payload = json.loads(matching[0]["payload"])
    assert payload["action_id"] == str(action.id)


async def test_two_concurrent_relay_workers_never_double_publish_the_same_message(
    db_available: bool, redis_client: Redis
) -> None:
    """NFR-SCL-001 ("Horizontal API va worker; stateless handler") names
    'ikki instansda test' as its own verification method — never actually
    run against this worker. The relay's docstring claims `FOR UPDATE
    SKIP LOCKED` "lets multiple relay workers run concurrently without
    double-processing a row", but nothing had ever exercised two relay
    workers racing for the same pending rows; this proves the claim
    rather than trusting the comment. Ten pending messages, two
    concurrent `relay_once` calls (a real asyncio.gather, not sequential
    awaits — each call's own DB round-trips give the other a genuine
    chance to interleave) — every message must be delivered exactly
    once between them, never twice, never zero times.
    """
    # Drain first, or ANY pending row another test left behind lands in these
    # two workers' batches and inflates the count below (see
    # _relay_until_drained). Observed for real — a run that added three
    # action-proposing tests elsewhere failed here with `assert 13 == 10`,
    # nothing to do with this test's own subject. The per-message assertion
    # further down is what proves exactly-once; this makes the "ten units of
    # work between them" count mean this test's ten.
    await _relay_until_drained(redis_client)

    customer_id = uuid.uuid4()
    action_ids = []
    async with tenant_scoped_session(customer_id) as session:
        for i in range(10):
            action, _ = await propose_action(
                session,
                customer_id=customer_id,
                workspace_id=uuid.uuid4(),
                trace_id=uuid.uuid4(),
                actor_id="user:alice",
                tool_name="knowledge.read",
                risk_level=RiskLevel.R1,
                payload={"query": f"report {i}"},
                idempotency_key=f"idem-concurrent-relay-{i}",
            )
            await validate_action(session, action, actor_id="user:alice")
            action_ids.append(action.id)

    counts = await asyncio.gather(
        relay_once(redis_client, batch_size=10), relay_once(redis_client, batch_size=10)
    )
    assert sum(counts) == 10  # every message delivered, by exactly one of the two workers

    stream = "doda:outbox:action.ready.v1"
    entries = await redis_client.xrange(stream)
    delivered_ids = [
        fields["aggregate_id"]
        for _entry_id, fields in entries
        if fields["aggregate_id"] in {str(a) for a in action_ids}
    ]
    assert sorted(delivered_ids) == sorted(str(a) for a in action_ids)  # no duplicates, none missing


async def test_run_forever_delivers_then_stops_promptly_on_stop_event(
    db_available: bool, redis_client: Redis
) -> None:
    """`run_forever` is the actual worker loop (previously nothing in this
    codebase ever called `relay_once` outside of a test) — proves it
    delivers a real message end-to-end AND honors a shutdown signal
    immediately rather than only after finishing an arbitrary sleep.
    """
    customer_id = uuid.uuid4()
    workspace_id, trace_id = uuid.uuid4(), uuid.uuid4()

    async with tenant_scoped_session(customer_id) as session:
        action, _ = await propose_action(
            session,
            customer_id=customer_id,
            workspace_id=workspace_id,
            trace_id=trace_id,
            actor_id="user:alice",
            tool_name="knowledge.read",
            risk_level=RiskLevel.R1,
            payload={"query": "quarterly report"},
            idempotency_key="idem-run-forever-test",
        )
        await validate_action(session, action, actor_id="user:alice")

    stop_event = asyncio.Event()
    task = asyncio.create_task(run_forever(redis_client, stop_event=stop_event, poll_interval=0.05))

    stream = "doda:outbox:action.ready.v1"
    for _ in range(100):
        entries = await redis_client.xrange(stream)
        if any(fields.get("aggregate_id") == str(action.id) for _entry_id, fields in entries):
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("run_forever never delivered the message")

    stop_event.set()
    await asyncio.wait_for(task, timeout=2)  # would time out if stop_event were ignored


async def test_run_forever_notices_stop_event_promptly_while_idle(
    db_available: bool, redis_client: Redis
) -> None:
    """With nothing pending, the loop must sleep between polls (not busy-loop)
    but still react to shutdown within about one poll_interval — not only
    after some much longer, unrelated timeout. A regression to a plain
    `asyncio.sleep(poll_interval)` (ignoring stop_event mid-sleep) would
    make this test time out.
    """
    stop_event = asyncio.Event()
    task = asyncio.create_task(run_forever(redis_client, stop_event=stop_event, poll_interval=0.05))
    await asyncio.sleep(0.1)  # let it complete at least one idle poll
    stop_event.set()
    await asyncio.wait_for(task, timeout=1)


async def test_main_stops_cleanly_on_sigterm(db_available: bool, redis_client: Redis) -> None:
    """The real worker entrypoint: registers SIGTERM/SIGINT handlers and
    exits `main()` when signaled, rather than requiring a hard kill."""
    task = asyncio.create_task(main())
    await asyncio.sleep(0.2)  # let it start and register the signal handlers
    assert_worker_still_running_before_signaling(task)
    os.kill(os.getpid(), signal.SIGTERM)
    await asyncio.wait_for(task, timeout=5)
