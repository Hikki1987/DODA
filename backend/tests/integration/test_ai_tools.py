"""Integration tests for `doda.application.ai_tools` — the one place a
model's tool call either executes immediately (READ) or proposes an
Action through the existing approval chain (WRITE), never the other way
around, and never skipping argument validation. Uses a real Postgres
session, since `dispatch_read_tool`/`propose_write_tool_action` both go
through application services that query/write real tables.
"""

import json
import uuid

import pytest

from doda.application.ai_tools import (
    ToolArgumentsInvalidError,
    ToolNotFoundError,
    dispatch_read_tool,
    is_read_tool,
    is_write_tool,
    propose_write_tool_action,
)
from doda.application.authz_service import WorkspaceContext
from doda.application.task_service import create_task
from doda.db import tenant_scoped_session
from doda.domain.action.models import ActionStatus
from doda.domain.security.roles import WorkspaceRole
from tests.integration.conftest import seed_workspace_member


def test_tool_categories_are_mutually_exclusive_and_exhaustive_for_the_known_tools() -> None:
    assert is_read_tool("list_my_open_tasks")
    assert not is_write_tool("list_my_open_tasks")
    assert is_write_tool("telegram_send_message")
    assert not is_read_tool("telegram_send_message")
    assert not is_read_tool("something_nobody_registered")
    assert not is_write_tool("something_nobody_registered")


async def test_dispatching_a_read_tool_with_no_open_tasks_says_so_plainly(db_available: bool) -> None:
    member = await seed_workspace_member()
    async with tenant_scoped_session(member.customer_id) as db:
        result = await dispatch_read_tool(
            db, tool_name="list_my_open_tasks", arguments_json="{}", workspace_id=member.workspace_id
        )
    assert result == "No open tasks."


async def test_dispatching_a_read_tool_lists_real_open_tasks_from_this_workspace_only(
    db_available: bool,
) -> None:
    member = await seed_workspace_member()
    other = await seed_workspace_member()
    async with tenant_scoped_session(member.customer_id) as db:
        await create_task(
            db,
            customer_id=member.customer_id,
            workspace_id=member.workspace_id,
            owner_id=f"user:{member.user_id}",
            title="Hisobotni tayyorlash",
        )
        await db.commit()

    async with tenant_scoped_session(member.customer_id) as db:
        result = await dispatch_read_tool(
            db, tool_name="list_my_open_tasks", arguments_json="{}", workspace_id=member.workspace_id
        )
    assert "Hisobotni tayyorlash" in result

    # The other seeded workspace (different customer) must never see it —
    # same FR-CONV-003/NFR-ISO-002 isolation the rest of this codebase
    # enforces everywhere else.
    async with tenant_scoped_session(other.customer_id) as db:
        other_result = await dispatch_read_tool(
            db, tool_name="list_my_open_tasks", arguments_json="{}", workspace_id=other.workspace_id
        )
    assert "Hisobotni tayyorlash" not in other_result


async def test_dispatching_a_read_tool_with_invalid_arguments_raises_a_typed_error_not_a_crash(
    db_available: bool,
) -> None:
    member = await seed_workspace_member()
    async with tenant_scoped_session(member.customer_id) as db:
        with pytest.raises(ToolArgumentsInvalidError):
            # limit is bounded 1..50 — a model-supplied 9999 must be
            # rejected by Pydantic validation, never silently clamped or
            # passed through to the query.
            await dispatch_read_tool(
                db,
                tool_name="list_my_open_tasks",
                arguments_json='{"limit": 9999}',
                workspace_id=member.workspace_id,
            )


async def test_dispatching_an_unknown_tool_name_raises_tool_not_found(db_available: bool) -> None:
    member = await seed_workspace_member()
    async with tenant_scoped_session(member.customer_id) as db:
        with pytest.raises(ToolNotFoundError):
            await dispatch_read_tool(
                db,
                tool_name="delete_the_whole_workspace",
                arguments_json="{}",
                workspace_id=member.workspace_id,
            )


async def test_proposing_a_write_tool_creates_an_r3_action_requiring_approval(db_available: bool) -> None:
    member = await seed_workspace_member()
    ctx = WorkspaceContext(
        customer_id=member.customer_id,
        workspace_id=member.workspace_id,
        user_id=member.user_id,
        role=WorkspaceRole.MEMBER,
    )
    async with tenant_scoped_session(member.customer_id) as db:
        action, approval = await propose_write_tool_action(
            db,
            tool_name="telegram_send_message",
            arguments_json=json.dumps({"chat_id": "123", "text": "salom"}),
            workspace_context=ctx,
            trace_id=uuid.uuid4(),
            idempotency_key="chat:conv-1:call-1",
        )
        await db.commit()

    # Every tool call is a proposal, never a completed action — 9.1/9.2's
    # risk-based approval chain, not something the AI layer decides for
    # itself (6.2: "AI qatlami authoritative avtorizatsiya qarorini
    # chiqarmaydi").
    assert action.tool_name == "telegram.send_message"
    assert action.risk_level.value == "R3"
    assert action.status is ActionStatus.AWAITING_APPROVAL
    assert approval is not None


async def test_a_retried_write_tool_call_collapses_onto_the_same_action_not_a_duplicate(
    db_available: bool,
) -> None:
    """The explicit instruction: a retried gateway call that re-surfaces
    'the same' tool call must never create a second Action — the
    deterministic idempotency key (conversation_id:call_id, built by
    `doda.application.conversation_service`) is what makes this collapse
    onto the existing row via propose_action's own UNIQUE constraint."""
    member = await seed_workspace_member()
    ctx = WorkspaceContext(
        customer_id=member.customer_id,
        workspace_id=member.workspace_id,
        user_id=member.user_id,
        role=WorkspaceRole.MEMBER,
    )
    args = json.dumps({"chat_id": "123", "text": "salom"})

    async with tenant_scoped_session(member.customer_id) as db:
        first_action, _ = await propose_write_tool_action(
            db,
            tool_name="telegram_send_message",
            arguments_json=args,
            workspace_context=ctx,
            trace_id=uuid.uuid4(),
            idempotency_key="chat:conv-1:call-1",
        )
        await db.commit()

    async with tenant_scoped_session(member.customer_id) as db:
        second_action, _ = await propose_write_tool_action(
            db,
            tool_name="telegram_send_message",
            arguments_json=args,
            workspace_context=ctx,
            trace_id=uuid.uuid4(),  # even a different trace_id — the key is what matters
            idempotency_key="chat:conv-1:call-1",
        )
        await db.commit()

    assert first_action.id == second_action.id


async def test_invalid_write_tool_arguments_are_rejected_before_any_action_is_created(
    db_available: bool,
) -> None:
    member = await seed_workspace_member()
    ctx = WorkspaceContext(
        customer_id=member.customer_id,
        workspace_id=member.workspace_id,
        user_id=member.user_id,
        role=WorkspaceRole.MEMBER,
    )
    async with tenant_scoped_session(member.customer_id) as db:
        with pytest.raises(ToolArgumentsInvalidError):
            await propose_write_tool_action(
                db,
                tool_name="telegram_send_message",
                arguments_json=json.dumps({"chat_id": "123"}),  # missing required "text"
                workspace_context=ctx,
                trace_id=uuid.uuid4(),
                idempotency_key="chat:conv-2:call-1",
            )
