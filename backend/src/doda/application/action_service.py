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
from doda.application.notification_service import create_notification
from doda.application.outbox_service import enqueue_outbox_message
from doda.domain.action.approval import DEFAULT_APPROVAL_TTL, Approval, ApprovalStatus
from doda.domain.action.models import AUTO_APPROVED_RISK_LEVELS, Action, ActionStatus, RiskLevel
from doda.domain.action.state_machine import InvalidActionTransition, transition
from doda.domain.action.tool_policy import enforce_minimum_risk_level
from doda.domain.base import utcnow
from doda.domain.identity.models import ActorKind
from doda.domain.notification.models import NotificationType

MAX_PAGE_SIZE = 200


class ApprovalInvalidError(Exception):
    """Raised when an approval cannot be consumed as-is (9.2 invariants)."""


class ServiceActorRiskLevelExceededError(Exception):
    """FR-AUTH-009 / 2.2's role table: a Service Actor's own maximum risk
    level is R2 — it can never propose an action that would require human
    approval, since it is also barred from ever consuming one
    (authorize_consume_approval). Raised before the Action row is even
    created (DRAFT), same "checked first" placement as the kill switch
    check right above it in propose_action."""

    def __init__(self, risk_level: RiskLevel) -> None:
        self.risk_level = risk_level
        super().__init__(
            f"a service actor may not propose a {risk_level.value} action (max is R2, FR-AUTH-009)"
        )


class MissingProviderReceiptError(Exception):
    """FR-ACT-007: raised when a caller tries to transition an Action to
    SUCCEEDED without supplying a provider receipt (apply_transition)."""

    def __init__(self, action_id: uuid.UUID) -> None:
        self.action_id = action_id
        super().__init__(f"cannot mark action {action_id} SUCCEEDED without a provider receipt (FR-ACT-007)")


class InvalidCompensationOutcomeError(Exception):
    """FR-ACT-009: raised when complete_compensation is given an `outcome`
    other than COMPENSATED or FAILED. A bare ValueError here would fall
    through to api/errors.py's generic 500 catch-all — unlike its sibling
    ActionNotCancellableError (same feature, same "invalid input to a
    state-transition function" shape), which already gets a registered
    404/409-style handler. This gives it the same treatment."""

    def __init__(self, outcome: ActionStatus) -> None:
        self.outcome = outcome
        super().__init__(f"complete_compensation outcome must be COMPENSATED or FAILED, got {outcome.value}")


class ActionNotCancellableError(Exception):
    """FR-ACT-009: raised when cancellation is requested for an action
    that is neither READY (cancels outright) nor RUNNING (requests a
    reversal instead — see request_cancellation). TRD 4.2's own state
    table gives no CANCELLED/COMPENSATING edge from any other status,
    including AWAITING_APPROVAL: "changed my mind before approval" is
    already covered by letting the approval expire or rejecting it, not
    by a separate cancel path."""

    def __init__(self, action_id: uuid.UUID, status: ActionStatus) -> None:
        self.action_id = action_id
        self.status = status
        super().__init__(f"action {action_id} in status {status.value} cannot be cancelled")


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
    actor_kind: ActorKind = ActorKind.HUMAN,
) -> tuple[Action, bool]:
    """Create a DRAFT action, or return the existing one for a repeated
    idempotency_key (FR-ACT-004) instead of creating a duplicate.

    Returns (action, created).

    FR-CTL-003: checked first, before even a DRAFT row is created — an
    engaged kill switch means no new action exists at all, not one that
    exists but is stuck.

    `risk_level` is raised to `tool_name`'s registered minimum, if any,
    before the row is created (`domain.action.tool_policy`) — a caller
    can request a HIGHER tier than a tool's floor, never a lower one, so
    a registered tool's approval/step-up requirement can't be skipped by
    under-declaring risk_level in the request body.

    15th security-review pass (FR-AUTH-009): this default let
    `ai_tools.propose_write_tool_action`'s call site silently inherit
    HUMAN and skip the Service Actor R2 cap entirely — a real, confirmed
    bypass, not a hypothetical one. Fixed at that call site (it now
    threads `actor_kind` through from `conversation_service.stream_message`,
    which takes it as a required keyword with no default of its own) —
    the default stays here only because every OTHER caller genuinely is
    always human and forcing them to say so at every call site would be
    pure ceremony, not a second layer of defense.
    """
    await assert_not_killed(session, customer_id=customer_id, workspace_id=workspace_id)
    risk_level = enforce_minimum_risk_level(tool_name, risk_level)
    if actor_kind is ActorKind.SERVICE and risk_level not in AUTO_APPROVED_RISK_LEVELS:
        raise ServiceActorRiskLevelExceededError(risk_level)

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
        # Scoped by workspace_id too, matching the unique constraint
        # (FR-ACT-004): two different workspaces choosing the same
        # caller-supplied key must never collide onto the same Action —
        # that would let a member of one workspace read another
        # workspace's action payload and pending approval nonce.
        existing = await session.scalar(
            select(Action).where(
                Action.customer_id == customer_id,
                Action.workspace_id == workspace_id,
                Action.idempotency_key == idempotency_key,
            )
        )
        assert existing is not None
        return existing, False

    await record_audit_event(
        session,
        customer_id=customer_id,
        workspace_id=workspace_id,
        trace_id=trace_id,
        actor_id=actor_id,
        event_type="action.proposed.v1",
        safe_metadata={"action_id": str(action.id), "tool_name": tool_name, "risk_level": risk_level.value},
    )
    return action, True


async def resolve_replay_approval(session: AsyncSession, action: Action, *, actor_id: str) -> Approval | None:
    """When `propose_action` returns `created=False` (an idempotent
    replay, FR-ACT-004), the caller must decide whether to also hand back
    the action's pending `Approval` — and that decision is a security
    rule, not a formatting detail: a pending `Approval.nonce` is a
    one-time credential meant for the original proposer alone
    (`ApprovalOut.nonce`'s own docstring), so it may only be returned to
    the SAME actor who originally proposed the action, never to whoever
    happens to replay a matching idempotency key (5th security-review
    finding — `api/actions.py`'s caller-chosen uuid4() key and
    `ai_tools.py`'s deterministic chat-derived key were each fixed with
    an identical `action.actor_id == actor_id` check, independently, in
    the same PR). Centralized here, at the one place a third future
    replay caller would otherwise have to remember to copy that check
    correctly, rather than duplicated per caller.

    Returns None whenever the action isn't AWAITING_APPROVAL or the
    caller isn't its original actor — the Action itself is already
    visible to any workspace member via GET .../actions/{id}, only the
    nonce is actor-scoped.
    """
    if action.status is not ActionStatus.AWAITING_APPROVAL or action.actor_id != actor_id:
        return None
    return await session.scalar(
        select(Approval).where(Approval.action_id == action.id).order_by(Approval.created_at.desc()).limit(1)
    )


async def apply_transition(
    session: AsyncSession,
    action: Action,
    target: ActionStatus,
    *,
    actor_id: str,
    receipt: dict[str, Any] | None = None,
) -> Action:
    """Validate+apply a state transition and audit it either way (4.2).

    Re-locks and refreshes `action` first (SELECT ... FOR UPDATE, same
    technique as audit_service's chain-tip row), since this is the single
    chokepoint every transition path (validate_action, consume_approval)
    goes through. Without this, two concurrent POST
    /approvals/{id}/consume calls carrying the same nonce — each loading
    `action`/`approval` before either committed — could both pass
    consume_approval's `approval.status is PENDING` check and both reach
    here, both (re)transitioning AWAITING_APPROVAL -> READY and each
    enqueueing their own outbox message: a one-time approval nonce
    consumed twice, with the resulting external side effect queued twice.
    Locking here is sufficient even though the race starts on `approval`,
    not `action`: the second call, once unblocked, sees the already-READY
    action and fails transition()'s own state-machine check, raising and
    rolling back that entire transaction — including its in-memory
    `approval.status = APPROVED` write, which never commits.

    FR-ACT-007 (Must): "Receipt'siz 'SUCCEEDED' holati yozilmaydi" — a
    caller transitioning to SUCCEEDED must supply `receipt`, a small
    dict describing what the external provider actually confirmed (e.g.
    Telegram's own message_id). Enforced here, the single chokepoint,
    rather than trusted to each connector — a worker that "forgot" to
    pass one gets a raised MissingProviderReceiptError instead of a
    silently unverified success. The receipt is recorded on the audit
    event for this transition (`provider_receipt` in safe_metadata), not
    just accepted and discarded.
    """
    if target is ActionStatus.SUCCEEDED and receipt is None:
        raise MissingProviderReceiptError(action.id)
    await session.execute(
        select(Action)
        .where(Action.id == action.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    previous = action.status
    try:
        action.status = transition(previous, target)
    except InvalidActionTransition:
        await record_audit_event(
            session,
            customer_id=action.customer_id,
            workspace_id=action.workspace_id,
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
        workspace_id=action.workspace_id,
        trace_id=action.trace_id,
        actor_id=actor_id,
        event_type=f"action.{target.value.lower()}.v1",
        safe_metadata={
            "action_id": str(action.id),
            "from": previous.value,
            "to": target.value,
            "provider_receipt": receipt,
        },
    )

    # FR-NTF-002: two of the four required notification types are action
    # transitions. Hooked here (not in validate_action) so any code path
    # that drives an action to these states notifies, not just this one.
    if target is ActionStatus.AWAITING_APPROVAL:
        await create_notification(
            session,
            customer_id=action.customer_id,
            workspace_id=action.workspace_id,
            recipient_id=action.actor_id,
            notification_type=NotificationType.PENDING_APPROVAL,
            reference_type="action",
            reference_id=action.id,
            safe_metadata={"tool_name": action.tool_name, "risk_level": action.risk_level.value},
        )
    elif target is ActionStatus.FAILED:
        await create_notification(
            session,
            customer_id=action.customer_id,
            workspace_id=action.workspace_id,
            recipient_id=action.actor_id,
            notification_type=NotificationType.FAILED_ACTION,
            reference_type="action",
            reference_id=action.id,
            safe_metadata={"tool_name": action.tool_name},
        )
    return action


async def request_cancellation(session: AsyncSession, action: Action, *, actor_id: str) -> Action:
    """FR-ACT-009 ("Action bekor qilish"): a READY action (validated,
    queued, but not yet picked up by a relay worker) cancels outright. A
    RUNNING action is already mid-flight — cancelling it means requesting
    a reversal instead, which the state machine models as RUNNING ->
    COMPENSATING, not a direct CANCELLED (see ActionNotCancellableError's
    own docstring for why no other status is accepted here). Rejecting
    those up front, before calling apply_transition, gives the caller a
    specific ActionNotCancellableError instead of the generic
    InvalidActionTransition apply_transition would otherwise raise.
    """
    if action.status is ActionStatus.READY:
        return await apply_transition(session, action, ActionStatus.CANCELLED, actor_id=actor_id)
    if action.status is ActionStatus.RUNNING:
        return await apply_transition(session, action, ActionStatus.COMPENSATING, actor_id=actor_id)
    raise ActionNotCancellableError(action.id, action.status)


async def complete_compensation(
    session: AsyncSession, action: Action, *, outcome: ActionStatus, actor_id: str
) -> Action:
    """FR-ACT-009's other half: COMPENSATING -> COMPENSATED, or ->
    FAILED if the reversal itself could not be carried out. There is no
    automated reversal to run here — Telegram's Bot API (the only
    connector today) exposes no message-delete/undo call this codebase's
    minimal client (infrastructure/telegram_client.py) uses, so
    completing a compensation is a human attesting they reversed the
    effect some other way (e.g. contacting the recipient directly). This
    is the same "no automated action, only a human-attested state
    change" honesty already applied elsewhere in this codebase
    (FR-ACT-007's receipt requirement, FR-TASK-005's reminder
    confirmation) rather than a fake automated "undo".

    `outcome` must be COMPENSATED or FAILED — checked here for a clear
    error message; apply_transition's own state-machine check would
    reject anything else anyway, since COMPENSATING has no other
    outgoing edge (TRD 4.2).
    """
    if outcome not in (ActionStatus.COMPENSATED, ActionStatus.FAILED):
        raise InvalidCompensationOutcomeError(outcome)
    return await apply_transition(session, action, outcome, actor_id=actor_id)


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
        raise ApprovalInvalidError(f"cannot request approval for action in status {action.status.value}")
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


async def list_actions_for_workspace(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    status: ActionStatus | None = None,
    limit: int = 50,
) -> list[Action]:
    """Every workspace member may see every action in their own workspace —
    the same visibility api/actions.py's existing get-by-id already grants
    (it checks workspace membership only, never actor identity); this list
    endpoint was simply missing until now, the same class of gap
    GET /v1/me/workspaces closed one level up."""
    query = select(Action).where(Action.workspace_id == workspace_id)
    if status is not None:
        query = query.where(Action.status == status)
    query = query.order_by(Action.created_at.desc()).limit(min(limit, MAX_PAGE_SIZE))
    result = await session.execute(query)
    return list(result.scalars())
