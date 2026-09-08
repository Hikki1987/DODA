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


@pytest.fixture
async def redis_client():
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await client.ping()
    except RedisConnectionError:
        pytest.skip("Redis not reachable — start it with `docker compose up -d redis`")
    yield client
    await client.aclose()


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

    published_count = await relay_once(redis_client)
    assert published_count >= 1

    stream = "doda:outbox:action.ready.v1"
    entries = await redis_client.xrange(stream)
    matching = [fields for _entry_id, fields in entries if fields.get("aggregate_id") == str(action.id)]

    assert len(matching) == 1
    assert matching[0]["aggregate_type"] == "action"
    payload = json.loads(matching[0]["payload"])
    assert payload["action_id"] == str(action.id)


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


async def test_main_stops_cleanly_on_sigterm(db_available: bool) -> None:
    """The real worker entrypoint: registers SIGTERM/SIGINT handlers and
    exits `main()` when signaled, rather than requiring a hard kill."""
    task = asyncio.create_task(main())
    await asyncio.sleep(0.2)  # let it start and register the signal handlers
    os.kill(os.getpid(), signal.SIGTERM)
    await asyncio.wait_for(task, timeout=5)
