"""Proves 9.2's one-time-nonce approval invariant actually holds under
concurrency, not just sequentially (the existing "approval already
{status}" test in test_action_service.py only calls consume_approval
twice in the same session, one after the other — it never proves the
check survives two requests that both loaded the approval before either
committed).

This is the test that would have failed against the old
apply_transition — no lock, no refresh — implementation: two concurrent
POST /approvals/{id}/consume calls carrying the same valid, still-PENDING
nonce could both pass every 9.2 check (nonce match, not expired, payload
unchanged, not already consumed) and both transition the action to READY,
each enqueueing its own outbox message — the one-time nonce consumed
twice, with the resulting external side effect queued twice. The fix lives
in apply_transition (the single chokepoint every transition, including
this one, goes through), so the loser here is rejected not by a re-checked
approval status but by apply_transition's own re-locked action state
(READY -> READY) — see its docstring.
"""

import asyncio
import uuid

from sqlalchemy import select

from doda.application.action_service import consume_approval, propose_action, submit_action_for_execution
from doda.db import tenant_scoped_session
from doda.domain.action.approval import Approval, ApprovalStatus
from doda.domain.action.models import Action, ActionStatus, RiskLevel
from doda.domain.action.state_machine import InvalidActionTransition
from doda.domain.outbox.models import OutboxMessage


async def test_two_concurrent_consumes_of_the_same_nonce_do_not_both_succeed(
    db_available: bool,
) -> None:
    customer_id = uuid.uuid4()
    workspace_id, trace_id = uuid.uuid4(), uuid.uuid4()

    async with tenant_scoped_session(customer_id) as session:
        action, _ = await propose_action(
            session,
            customer_id=customer_id,
            workspace_id=workspace_id,
            trace_id=trace_id,
            actor_id="user:proposer",
            tool_name="send_email",
            risk_level=RiskLevel.R3,
            payload={"to": "someone@example.com"},
            idempotency_key=str(uuid.uuid4()),
        )
        action, approval = await submit_action_for_execution(session, action, actor_id="user:proposer")
        assert approval is not None
        action_id, approval_id, nonce = action.id, approval.id, approval.nonce

    cm1 = tenant_scoped_session(customer_id)
    cm2 = tenant_scoped_session(customer_id)
    session1 = await cm1.__aenter__()
    session2 = await cm2.__aenter__()

    # Both "requests" load the still-PENDING approval before either one
    # has committed — the actual race window.
    approval1, action1 = await session1.get(Approval, approval_id), await session1.get(Action, action_id)
    approval2, action2 = await session2.get(Approval, approval_id), await session2.get(Action, action_id)
    assert approval1.status is ApprovalStatus.PENDING
    assert approval2.status is ApprovalStatus.PENDING

    async def consume(cm, session, action, approval, approver):
        try:
            await consume_approval(session, action, approval, approver_id=approver, nonce=nonce)
        except InvalidActionTransition as exc:
            # The second, unblocked consume sees the approval as still
            # PENDING (9.2's own check never re-validates it under lock),
            # but apply_transition's own re-lock-and-refresh then finds the
            # action already READY and rejects READY -> READY — the race
            # is closed one layer down, at the shared transition chokepoint.
            await cm.__aexit__(type(exc), exc, exc.__traceback__)
            return "rejected"
        else:
            await cm.__aexit__(None, None, None)
            return "ok"

    results = await asyncio.gather(
        consume(cm1, session1, action1, approval1, "user:approver1"),
        consume(cm2, session2, action2, approval2, "user:approver2"),
    )

    assert sorted(results) == ["ok", "rejected"]

    async with tenant_scoped_session(customer_id) as session:
        final_approval = await session.get(Approval, approval_id)
        final_action = await session.get(Action, action_id)
        outbox_messages = (
            (await session.execute(select(OutboxMessage).where(OutboxMessage.aggregate_id == action_id)))
            .scalars()
            .all()
        )

    assert final_approval.status is ApprovalStatus.APPROVED
    assert final_action.status is ActionStatus.READY
    # Not two — the one-time nonce was consumed exactly once, so the
    # resulting external side effect is enqueued exactly once too.
    assert len(outbox_messages) == 1
