"""End-to-end action lifecycle against a live PostgreSQL — exercises the
state machine (4.2), risk-based routing (9.1), approval invariants (9.2),
idempotency (FR-ACT-004) and the outbox (FR-ACT-008) together, the way a
real caller would use doda.application.action_service.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from doda.application.action_service import (
    ApprovalInvalidError,
    consume_approval,
    propose_action,
    request_approval,
    validate_action,
)
from doda.application.hashing import hash_payload
from doda.domain.action.approval import ApprovalStatus
from doda.domain.action.models import Action, ActionStatus, RiskLevel
from doda.domain.base import utcnow
from doda.domain.outbox.models import OutboxMessage


def _new_ids() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    return uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


async def test_low_risk_action_auto_advances_to_ready_and_enqueues_outbox(
    tenant_session,
) -> None:
    customer_id, session = tenant_session
    workspace_id, trace_id = uuid.uuid4(), uuid.uuid4()

    action, created = await propose_action(
        session,
        customer_id=customer_id,
        workspace_id=workspace_id,
        trace_id=trace_id,
        actor_id="user:alice",
        tool_name="knowledge.read",
        risk_level=RiskLevel.R1,
        payload={"query": "quarterly report"},
        idempotency_key="idem-1",
    )
    assert created is True

    await validate_action(session, action, actor_id="user:alice")

    assert action.status is ActionStatus.READY

    outbox_rows = (
        await session.execute(
            select(OutboxMessage).where(OutboxMessage.aggregate_id == action.id)
        )
    ).scalars().all()
    assert len(outbox_rows) == 1
    assert outbox_rows[0].event_type == "action.ready.v1"
    assert outbox_rows[0].published_at is None


async def test_high_risk_action_requires_approval_before_ready(tenant_session) -> None:
    customer_id, session = tenant_session
    workspace_id, trace_id = uuid.uuid4(), uuid.uuid4()

    action, _ = await propose_action(
        session,
        customer_id=customer_id,
        workspace_id=workspace_id,
        trace_id=trace_id,
        actor_id="user:alice",
        tool_name="email.send",
        risk_level=RiskLevel.R3,
        payload={"to": "boss@example.com", "subject": "Q3 numbers"},
        idempotency_key="idem-2",
    )

    await validate_action(session, action, actor_id="user:alice")
    assert action.status is ActionStatus.AWAITING_APPROVAL

    approval = await request_approval(session, action)
    assert approval.status is ApprovalStatus.PENDING
    assert approval.payload_hash == action.payload_hash

    await consume_approval(
        session, action, approval, approver_id="user:approver", nonce=approval.nonce
    )

    assert action.status is ActionStatus.READY
    assert approval.status is ApprovalStatus.APPROVED

    outbox_rows = (
        await session.execute(
            select(OutboxMessage).where(OutboxMessage.aggregate_id == action.id)
        )
    ).scalars().all()
    assert any(row.event_type == "action.ready.v1" for row in outbox_rows)


async def test_approval_rejected_if_payload_changed_after_approval_requested(
    tenant_session,
) -> None:
    """9.2: 'Approval aniq action payload hash'iga bog'lanadi; payload
    o'zgarsa approval avtomatik bekor bo'ladi.' A caller that mutates a
    proposed action's payload after approval was requested must not be able
    to sneak the new payload through on the old approval."""
    customer_id, session = tenant_session
    workspace_id, trace_id = uuid.uuid4(), uuid.uuid4()

    action, _ = await propose_action(
        session,
        customer_id=customer_id,
        workspace_id=workspace_id,
        trace_id=trace_id,
        actor_id="user:alice",
        tool_name="email.send",
        risk_level=RiskLevel.R3,
        payload={"to": "boss@example.com", "amount": 100},
        idempotency_key="idem-3",
    )
    await validate_action(session, action, actor_id="user:alice")
    approval = await request_approval(session, action)

    # Simulate the payload being swapped after the human saw the preview.
    action.payload = {"to": "boss@example.com", "amount": 100_000}
    action.payload_hash = hash_payload(action.payload)
    await session.flush()

    with pytest.raises(ApprovalInvalidError, match="payload changed"):
        await consume_approval(
            session, action, approval, approver_id="user:approver", nonce=approval.nonce
        )

    assert action.status is ActionStatus.REJECTED
    assert approval.status is ApprovalStatus.DENIED


async def test_wrong_nonce_does_not_consume_the_approval(tenant_session) -> None:
    customer_id, session = tenant_session
    workspace_id, trace_id = uuid.uuid4(), uuid.uuid4()

    action, _ = await propose_action(
        session,
        customer_id=customer_id,
        workspace_id=workspace_id,
        trace_id=trace_id,
        actor_id="user:alice",
        tool_name="email.send",
        risk_level=RiskLevel.R3,
        payload={"to": "boss@example.com"},
        idempotency_key="idem-4",
    )
    await validate_action(session, action, actor_id="user:alice")
    approval = await request_approval(session, action)

    with pytest.raises(ApprovalInvalidError, match="nonce mismatch"):
        await consume_approval(
            session, action, approval, approver_id="user:approver", nonce="wrong-nonce"
        )

    assert approval.status is ApprovalStatus.PENDING
    assert action.status is ActionStatus.AWAITING_APPROVAL


async def test_expired_approval_is_rejected_and_action_moves_to_expired(
    tenant_session,
) -> None:
    customer_id, session = tenant_session
    workspace_id, trace_id = uuid.uuid4(), uuid.uuid4()

    action, _ = await propose_action(
        session,
        customer_id=customer_id,
        workspace_id=workspace_id,
        trace_id=trace_id,
        actor_id="user:alice",
        tool_name="email.send",
        risk_level=RiskLevel.R3,
        payload={"to": "boss@example.com"},
        idempotency_key="idem-5",
    )
    await validate_action(session, action, actor_id="user:alice")
    approval = await request_approval(session, action)
    approval.expires_at = utcnow() - timedelta(seconds=1)
    await session.flush()

    with pytest.raises(ApprovalInvalidError, match="expired"):
        await consume_approval(
            session, action, approval, approver_id="user:approver", nonce=approval.nonce
        )

    assert action.status is ActionStatus.EXPIRED
    assert approval.status is ApprovalStatus.EXPIRED


async def test_duplicate_idempotency_key_returns_same_action_not_a_new_one(
    tenant_session,
) -> None:
    customer_id, session = tenant_session
    workspace_id, trace_id = uuid.uuid4(), uuid.uuid4()
    kwargs = dict(
        customer_id=customer_id,
        workspace_id=workspace_id,
        trace_id=trace_id,
        actor_id="user:alice",
        tool_name="email.send",
        risk_level=RiskLevel.R3,
        payload={"to": "boss@example.com"},
        idempotency_key="idem-shared",
    )

    first, first_created = await propose_action(session, **kwargs)
    second, second_created = await propose_action(session, **kwargs)

    assert first_created is True
    assert second_created is False
    assert first.id == second.id

    rows = (
        await session.execute(
            select(Action).where(
                Action.customer_id == customer_id, Action.idempotency_key == "idem-shared"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
