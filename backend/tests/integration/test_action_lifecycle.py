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
    ActionNotCancellableError,
    ApprovalInvalidError,
    InvalidCompensationOutcomeError,
    MissingProviderReceiptError,
    apply_transition,
    complete_compensation,
    consume_approval,
    propose_action,
    request_approval,
    request_cancellation,
    validate_action,
)
from doda.application.hashing import hash_payload
from doda.domain.action.approval import ApprovalStatus
from doda.domain.action.models import Action, ActionStatus, RiskLevel
from doda.domain.audit.models import AuditEvent
from doda.domain.base import utcnow
from doda.domain.identity.models import ActorKind
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
        actor_kind=ActorKind.HUMAN,
    )
    assert created is True

    await validate_action(session, action, actor_id="user:alice")

    assert action.status is ActionStatus.READY

    outbox_rows = (
        (await session.execute(select(OutboxMessage).where(OutboxMessage.aggregate_id == action.id)))
        .scalars()
        .all()
    )
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
        actor_kind=ActorKind.HUMAN,
    )

    await validate_action(session, action, actor_id="user:alice")
    assert action.status is ActionStatus.AWAITING_APPROVAL

    approval = await request_approval(session, action)
    assert approval.status is ApprovalStatus.PENDING
    assert approval.payload_hash == action.payload_hash

    await consume_approval(session, action, approval, approver_id="user:approver", nonce=approval.nonce)

    assert action.status is ActionStatus.READY
    assert approval.status is ApprovalStatus.APPROVED

    outbox_rows = (
        (await session.execute(select(OutboxMessage).where(OutboxMessage.aggregate_id == action.id)))
        .scalars()
        .all()
    )
    assert any(row.event_type == "action.ready.v1" for row in outbox_rows)


async def test_registered_tool_cannot_be_under_declared_below_its_minimum_risk(
    tenant_session,
) -> None:
    """OD-002 (Telegram, first connector): a member proposing
    telegram.send_message with a self-declared R0 must not skip
    approval/step-up — domain.action.tool_policy raises it to the
    registered R3 floor before the Action row is even created, so this
    proves the real, DB-backed propose_action call applies it, not just
    the pure policy function in isolation."""
    customer_id, session = tenant_session
    workspace_id, trace_id = uuid.uuid4(), uuid.uuid4()

    action, _ = await propose_action(
        session,
        customer_id=customer_id,
        workspace_id=workspace_id,
        trace_id=trace_id,
        actor_id="user:alice",
        tool_name="telegram.send_message",
        risk_level=RiskLevel.R0,  # under-declared — must be raised to R3
        payload={"chat_id": "123", "text": "hello"},
        idempotency_key="idem-telegram-1",
        actor_kind=ActorKind.HUMAN,
    )

    assert action.risk_level is RiskLevel.R3

    await validate_action(session, action, actor_id="user:alice")

    # R3 requires approval — the under-declared R0 must not have let this
    # auto-advance straight to READY.
    assert action.status is ActionStatus.AWAITING_APPROVAL


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
        actor_kind=ActorKind.HUMAN,
    )
    await validate_action(session, action, actor_id="user:alice")
    approval = await request_approval(session, action)

    # Simulate the payload being swapped after the human saw the preview.
    action.payload = {"to": "boss@example.com", "amount": 100_000}
    action.payload_hash = hash_payload(action.payload)
    await session.flush()

    with pytest.raises(ApprovalInvalidError, match="payload changed"):
        await consume_approval(session, action, approval, approver_id="user:approver", nonce=approval.nonce)

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
        actor_kind=ActorKind.HUMAN,
    )
    await validate_action(session, action, actor_id="user:alice")
    approval = await request_approval(session, action)

    with pytest.raises(ApprovalInvalidError, match="nonce mismatch"):
        await consume_approval(session, action, approval, approver_id="user:approver", nonce="wrong-nonce")

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
        actor_kind=ActorKind.HUMAN,
    )
    await validate_action(session, action, actor_id="user:alice")
    approval = await request_approval(session, action)
    approval.expires_at = utcnow() - timedelta(seconds=1)
    await session.flush()

    with pytest.raises(ApprovalInvalidError, match="expired"):
        await consume_approval(session, action, approval, approver_id="user:approver", nonce=approval.nonce)

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
        actor_kind=ActorKind.HUMAN,
    )

    first, first_created = await propose_action(session, **kwargs)
    second, second_created = await propose_action(session, **kwargs)

    assert first_created is True
    assert second_created is False
    assert first.id == second.id

    rows = (
        (
            await session.execute(
                select(Action).where(
                    Action.customer_id == customer_id, Action.idempotency_key == "idem-shared"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


# FR-ACT-007 (Must): "Receipt'siz 'SUCCEEDED' holati yozilmaydi".


async def _running_action(tenant_session) -> tuple[uuid.UUID, object, Action]:
    customer_id, session = tenant_session
    workspace_id, trace_id = uuid.uuid4(), uuid.uuid4()
    action, _ = await propose_action(
        session,
        customer_id=customer_id,
        workspace_id=workspace_id,
        trace_id=trace_id,
        actor_id="user:alice",
        tool_name="knowledge.read",
        risk_level=RiskLevel.R0,
        payload={"query": "hi"},
        idempotency_key="idem-receipt-1",
        actor_kind=ActorKind.HUMAN,
    )
    await validate_action(session, action, actor_id="user:alice")
    assert action.status is ActionStatus.READY
    await apply_transition(session, action, ActionStatus.RUNNING, actor_id="worker:test")
    return customer_id, session, action


async def test_succeeded_without_a_receipt_is_rejected(tenant_session) -> None:
    _, session, action = await _running_action(tenant_session)

    with pytest.raises(MissingProviderReceiptError):
        await apply_transition(session, action, ActionStatus.SUCCEEDED, actor_id="worker:test")

    # The rejected attempt must not have silently applied the transition.
    assert action.status is ActionStatus.RUNNING


async def test_succeeded_with_a_receipt_records_it_on_the_audit_event(tenant_session) -> None:
    customer_id, session, action = await _running_action(tenant_session)

    await apply_transition(
        session,
        action,
        ActionStatus.SUCCEEDED,
        actor_id="worker:test",
        receipt={"message_id": 42},
    )
    assert action.status is ActionStatus.SUCCEEDED

    event = (
        await session.execute(
            select(AuditEvent).where(
                AuditEvent.customer_id == customer_id,
                AuditEvent.event_type == "action.succeeded.v1",
            )
        )
    ).scalar_one()
    assert event.safe_metadata["provider_receipt"] == {"message_id": 42}


# FR-ACT-009 (Should): "Action bekor qilish va compensating amal" —
# "COMPENSATING -> COMPENSATED oqimi test bilan qoplangan".


async def _ready_action(tenant_session, *, idempotency_key: str) -> tuple[uuid.UUID, object, Action]:
    customer_id, session = tenant_session
    workspace_id, trace_id = uuid.uuid4(), uuid.uuid4()
    action, _ = await propose_action(
        session,
        customer_id=customer_id,
        workspace_id=workspace_id,
        trace_id=trace_id,
        actor_id="user:alice",
        tool_name="knowledge.read",
        risk_level=RiskLevel.R0,
        payload={"query": "hi"},
        idempotency_key=idempotency_key,
        actor_kind=ActorKind.HUMAN,
    )
    await validate_action(session, action, actor_id="user:alice")
    assert action.status is ActionStatus.READY
    return customer_id, session, action


async def test_cancelling_a_ready_action_moves_it_straight_to_cancelled(tenant_session) -> None:
    _, session, action = await _ready_action(tenant_session, idempotency_key="idem-cancel-ready")

    await request_cancellation(session, action, actor_id="user:alice")

    assert action.status is ActionStatus.CANCELLED


async def test_cancelling_a_running_action_requests_compensation_instead(tenant_session) -> None:
    _, session, action = await _ready_action(tenant_session, idempotency_key="idem-cancel-running")
    await apply_transition(session, action, ActionStatus.RUNNING, actor_id="worker:test")

    await request_cancellation(session, action, actor_id="user:alice")

    # RUNNING has no direct CANCELLED edge (TRD 4.2) — cancelling an
    # in-flight action means requesting its reversal, not pretending it
    # never happened.
    assert action.status is ActionStatus.COMPENSATING


async def test_cancelling_an_already_terminal_action_is_rejected(tenant_session) -> None:
    customer_id, session, action = await _running_action(tenant_session)
    await apply_transition(
        session, action, ActionStatus.SUCCEEDED, actor_id="worker:test", receipt={"message_id": 1}
    )

    with pytest.raises(ActionNotCancellableError):
        await request_cancellation(session, action, actor_id="user:alice")

    # The rejected attempt must not have silently touched the action.
    assert action.status is ActionStatus.SUCCEEDED


async def test_compensation_completes_to_compensated(tenant_session) -> None:
    customer_id, session, action = await _ready_action(tenant_session, idempotency_key="idem-compensate-ok")
    await apply_transition(session, action, ActionStatus.RUNNING, actor_id="worker:test")
    await request_cancellation(session, action, actor_id="user:alice")
    assert action.status is ActionStatus.COMPENSATING

    await complete_compensation(session, action, outcome=ActionStatus.COMPENSATED, actor_id="admin:bob")

    assert action.status is ActionStatus.COMPENSATED
    event = (
        await session.execute(
            select(AuditEvent).where(
                AuditEvent.customer_id == customer_id,
                AuditEvent.event_type == "action.compensated.v1",
            )
        )
    ).scalar_one()
    assert event.safe_metadata["from"] == "COMPENSATING"
    assert event.safe_metadata["to"] == "COMPENSATED"


async def test_compensation_can_also_end_in_failed_if_the_reversal_could_not_be_done(tenant_session) -> None:
    _, session, action = await _ready_action(tenant_session, idempotency_key="idem-compensate-fail")
    await apply_transition(session, action, ActionStatus.RUNNING, actor_id="worker:test")
    await request_cancellation(session, action, actor_id="user:alice")

    await complete_compensation(session, action, outcome=ActionStatus.FAILED, actor_id="admin:bob")

    assert action.status is ActionStatus.FAILED


async def test_complete_compensation_rejects_any_other_outcome(tenant_session) -> None:
    _, session, action = await _ready_action(tenant_session, idempotency_key="idem-compensate-bad-outcome")
    await apply_transition(session, action, ActionStatus.RUNNING, actor_id="worker:test")
    await request_cancellation(session, action, actor_id="user:alice")

    with pytest.raises(InvalidCompensationOutcomeError, match="COMPENSATED or FAILED"):
        await complete_compensation(session, action, outcome=ActionStatus.READY, actor_id="admin:bob")

    # The rejected attempt must not have silently touched the action.
    assert action.status is ActionStatus.COMPENSATING
