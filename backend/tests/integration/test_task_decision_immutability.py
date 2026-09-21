"""FR-TASK-003's own acceptance criterion ("Qaror versiyalanadi; oldingi
versiya o'chirilmaydi") is asserted directly here, not just observed —
the same discipline `test_audit_events_reject_update_and_delete` already
applies to audit_events. Until this test exists, a migration that
dropped the 0020 trigger (or a downgrade that left it off) would take
the whole append-only guarantee with it and every other test would
still pass, since none of them attempt an UPDATE/DELETE."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from doda.application.task_service import create_task, record_task_decision
from doda.db import tenant_scoped_session
from doda.domain.task.models import TaskDecision


async def test_task_decisions_reject_update_and_delete(db_available: bool) -> None:
    customer_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        task = await create_task(
            session,
            customer_id=customer_id,
            workspace_id=workspace_id,
            owner_id="user:writer",
            title="Pick a cache backend",
        )
        record = await record_task_decision(
            session,
            task,
            actor_id="user:writer",
            variant="Postgres vs SQLite",
            tradeoff="server dependency vs no concurrent writers",
            decision="Postgres",
            reason="already required elsewhere",
        )
        record_id = record.id

    for statement, operation in (
        (text("UPDATE task_decisions SET decision = 'Redis' WHERE id = :id"), "UPDATE"),
        (text("DELETE FROM task_decisions WHERE id = :id"), "DELETE"),
    ):
        async with tenant_scoped_session(customer_id) as session:
            with pytest.raises(DBAPIError) as excinfo:
                await session.execute(statement, {"id": record_id})
            assert "append-only" in str(excinfo.value), f"{operation} must be refused by the trigger"

    # Still there, unchanged — the refusals were not a partial write.
    async with tenant_scoped_session(customer_id) as session:
        survivor = await session.get(TaskDecision, record_id)
        assert survivor is not None
        assert survivor.decision == "Postgres"
