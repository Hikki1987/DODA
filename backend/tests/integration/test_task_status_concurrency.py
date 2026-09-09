"""Proves a fix mirroring FR-AUD-004's audit-chain-fork fix, applied to
task_service.change_task_status: two requests that both loaded the same
task while it was still TODO, racing to advance it, must not both succeed
and both write a TaskHistory row for the same transition. This is the
test that would have failed against the old "read task.status from
whatever the caller already loaded, no lock" implementation — two
concurrent transactions could both see TODO and both commit a
TODO -> IN_PROGRESS move.

Each "request" gets its own session/connection and explicitly controls
when it commits (mirroring the get_request_context dependency's
commit-at-end-of-request lifecycle) so the two writers' reads and writes
genuinely interleave, rather than accidentally serializing the way two
independent asyncio.gather'd coroutines that each open+commit+close in one
breath tend to in practice.
"""

import asyncio
import uuid

from sqlalchemy import select

from doda.application.task_service import InvalidTaskTransition, change_task_status, create_task
from doda.db import tenant_scoped_session
from doda.domain.task.models import Task, TaskHistory, TaskStatus


async def test_two_concurrent_requests_advancing_the_same_task_do_not_double_write_history(
    db_available: bool,
) -> None:
    customer_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    async with tenant_scoped_session(customer_id) as session:
        task = await create_task(
            session,
            customer_id=customer_id,
            workspace_id=workspace_id,
            owner_id="user:owner",
            title="concurrency task",
        )
        task_id = task.id

    cm1 = tenant_scoped_session(customer_id)
    cm2 = tenant_scoped_session(customer_id)
    session1 = await cm1.__aenter__()
    session2 = await cm2.__aenter__()

    # Both "requests" load the task while it's still TODO, before either
    # one has committed a transition — the actual race window.
    t1 = await session1.get(Task, task_id)
    t2 = await session2.get(Task, task_id)
    assert t1.status is TaskStatus.TODO
    assert t2.status is TaskStatus.TODO

    async def advance(cm, session, task, actor):
        try:
            await change_task_status(session, task, target=TaskStatus.IN_PROGRESS, actor_id=actor)
        except InvalidTaskTransition as exc:
            await cm.__aexit__(type(exc), exc, exc.__traceback__)
            return "rejected"
        else:
            await cm.__aexit__(None, None, None)
            return "ok"

    results = await asyncio.gather(
        advance(cm1, session1, t1, "user:w1"),
        advance(cm2, session2, t2, "user:w2"),
    )

    # Exactly one of the two racing requests wins; the other is correctly
    # rejected once it sees the real (locked, refreshed) status instead of
    # its own stale read.
    assert sorted(results) == ["ok", "rejected"]

    async with tenant_scoped_session(customer_id) as session:
        final_task = await session.get(Task, task_id)
        history = (
            (await session.execute(select(TaskHistory).where(TaskHistory.task_id == task_id))).scalars().all()
        )

    assert final_task.status is TaskStatus.IN_PROGRESS
    # Birth-into-TODO row + exactly one TODO -> IN_PROGRESS row, not two.
    assert len(history) == 2
    transitions = [(h.from_status, h.to_status) for h in history]
    assert transitions.count((TaskStatus.TODO, TaskStatus.IN_PROGRESS)) == 1
