"""Action lifecycle orchestration — TRD sections 4.2 (state machine), 9.1
(risk-based approval routing) and 9.2 (approval invariants). This is the
Application layer (6.1): it orchestrates Domain objects, the outbox and
audit, but contains no transport or authorization-decision code itself —
callers are expected to have already run authz before calling here.
"""

import secrets
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from doda.application.audit_service import record_audit_event
from doda.application.hashing import hash_payload
from doda.application.kill_switch_service import assert_not_killed
from doda.application.outbox_service import enqueue_outbox_message
from doda.domain.action.approval import DEFAULT_APPROVAL_TTL, Approval, ApprovalStatus
from doda.domain.action.models import AUTO_APPROVED_RISK_LEVELS, Action, ActionStatus, RiskLevel
from doda.domain.action.state_machine import InvalidActionTransition, transition
from doda.domain.base import utcnow


class ApprovalInvalidError(Exception):
    """Raised when an approval cannot be consumed as-is (9.2 invariants)."""


async def propose_action(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    workspace_id: uuid.UUID,
    trace_id: uuid.UUID,
    actor_id: str,
    tool_name: str,
    risk_level: RiskLevel,
    payload: dict[str, Any],
    idempotency_key: str,
    task_id: uuid.UUID | None = None,
) -> tuple[Action, bool]:
    """Create a DRAFT action, or return the existing one for a repeated
    idempotency_key (FR-ACT-004) instead of creating a duplicate.

    Returns (action, created).

    FR-CTL-003: checked first, before even a DRAFT row is created — an
    engaged kill switch means no new action exists at all, not one that
    exists but is stuck.
    """
    await assert_not_killed(session, customer_id=customer_id, workspace_id=workspace_id)

    action = Action(
        customer_id=customer_id,
        workspace_id=workspace_id,
        trace_id=trace_id,
        task_id=task_id,
        actor_id=actor_id,
        tool_name=tool_name,
        risk_level=risk_level,
        payload=payload,
        payload_hash=hash_payload(payload),
        idempotency_key=idempotency_key,
        status=ActionStatus.DRAFT,
    )
    try:
        async with session.begin_nested():
            session.add(action)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(Action).where(
                Action.customer_id == customer_id,
                Action.idempotency_key == idempotency_key,
            )
        )
        assert existing is not None
        return existing, False

    await record_audit_event(
        session,
        customer_id=customer_id,
        trace_id=trace_id,
        actor_id=actor_id,
        event_type="action.proposed.v1",
        safe_metadata={"action_id": str(action.id), "tool_name": tool_name, "risk_level": risk_level.value},
    )
    return action, True


async def apply_transition(
    session: AsyncSession, action: Action, target: ActionStatus, *, actor_id: str
) -> Action:
    """Validate+apply a state transition and audit it either way (4.2)."""
    previous = action.status
    try:
        action.status = transition(previous, target)
    except InvalidActionTransition:
        await record_audit_event(
            session,
            customer_id=action.customer_id,
            trace_id=action.trace_id,
            actor_id=actor_id,
            event_type="action.transition_rejected.v1",
            safe_metadata={"action_id": str(action.id), "from": previous.value, "to": target.value},
        )
        raise
    await session.flush()
    await record_audit_event(
        session,
        customer_id=action.customer_id,
        trace_id=action.trace_id,
        actor_id=actor_id,
        event_type=f"action.{target.value.lower()}.v1",
        safe_metadata={"action_id": str(action.id), "from": previous.value, "to": target.value},
    )
    return action


async def validate_action(session: AsyncSession, action: Action, *, actor_id: str) -> Action:
    """VALIDATING, then either straight to READY (R0-R2, 9.1) or
    AWAITING_APPROVAL (R3+). Enqueues the outbox message that lets a worker
    pick up a READY action, in the same transaction as the state change.
    """
    await apply_transition(session, action, ActionStatus.VALIDATING, actor_id=actor_id)

    if action.risk_level in AUTO_APPROVED_RISK_LEVELS:
        await apply_transition(session, action, ActionStatus.READY, actor_id=actor_id)
        await enqueue_outbox_message(
            session,
            customer_id=action.customer_id,
            aggregate_type="action",
            aggregate_id=action.id,
            event_type="action.ready.v1",
            payload={"action_id": str(action.id), "tool_name": action.tool_name},
        )
    else:
        await apply_transition(session, action, ActionStatus.AWAITING_APPROVAL, actor_id=actor_id)

    return action


async def submit_action_for_execution(
    session: AsyncSession, action: Action, *, actor_id: str
) -> tuple[Action, Approval | None]:
    """The use case an API caller actually wants after proposing an action:
    validate it, and if that routes to AWAITING_APPROVAL, immediately create
    the Approval too so the caller has something to show a human — matching
    UC-004's flow where the approval preview appears right after risk
    classification, not as a separate round trip.
    """
    await validate_action(session, action, actor_id=actor_id)
    if action.status is ActionStatus.AWAITING_APPROVAL:
        approval = await request_approval(session, action)
        return action, approval
    return action, None


async def request_approval(session: AsyncSession, action: Action) -> Approval:
    """Create a fresh approval bound to the action's current payload_hash
    (9.2). Only meaningful while the action is AWAITING_APPROVAL."""
    if action.status is not ActionStatus.AWAITING_APPROVAL:
        raise ApprovalInvalidError(
            f"cannot request approval for action in status {action.status.value}"
        )
    approval = Approval(
        customer_id=action.customer_id,
        action_id=action.id,
        payload_hash=action.payload_hash,
        nonce=secrets.token_urlsafe(32),
        status=ApprovalStatus.PENDING,
        expires_at=utcnow() + DEFAULT_APPROVAL_TTL,
    )
    session.add(approval)
    await session.flush()
    return approval


async def consume_approval(
    session: AsyncSession,
    action: Action,
    approval: Approval,
    *,
    approver_id: str,
    nonce: str,
) -> Action:
    """Approve the action if, and only if, every 9.2 invariant holds:
    matching one-time nonce, not expired, not already consumed, and the
    action's payload unchanged since the approval was requested. A failed
    check denies/expires the approval and moves the action to a terminal
    state rather than leaving it pending — a bypass attempt must leave a
    trace, not a silent no-op (release-blocker criterion, 15.2).
    """
    if approval.status is not ApprovalStatus.PENDING:
        raise ApprovalInvalidError(f"approval already {approval.status.value}")
    if not secrets.compare_digest(approval.nonce, nonce):
        raise ApprovalInvalidError("nonce mismatch")

    if utcnow() > approval.expires_at:
        approval.status = ApprovalStatus.EXPIRED
        await apply_transition(session, action, ActionStatus.EXPIRED, actor_id=approver_id)
        raise ApprovalInvalidError("approval expired")

    if approval.payload_hash != action.payload_hash:
        approval.status = ApprovalStatus.DENIED
        await apply_transition(session, action, ActionStatus.REJECTED, actor_id=approver_id)
        raise ApprovalInvalidError("action payload changed since approval was requested")

    approval.status = ApprovalStatus.APPROVED
    approval.approver_id = approver_id
    await apply_transition(session, action, ActionStatus.READY, actor_id=approver_id)
    await enqueue_outbox_message(
        session,
        customer_id=action.customer_id,
        aggregate_type="action",
        aggregate_id=action.id,
        event_type="action.ready.v1",
        payload={"action_id": str(action.id), "tool_name": action.tool_name, "approval_id": str(approval.id)},
    )
    return action
