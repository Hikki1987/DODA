"""Action endpoints — Experience layer (6.1). Every handler receives its
tenant/authz context only via RequestContext (doda.api.dependencies); none
accepts customer_id or actor_id from the client, per CLAUDE.md's dependency
rules and the master instruction.
"""

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from doda.api.dependencies import RequestContext, get_request_context
from doda.api.schemas import (
    ActionOut,
    ApprovalOut,
    CompleteCompensationRequest,
    ConsumeApprovalRequest,
    ProposeActionRequest,
    SubmitActionResponse,
)
from doda.application.action_service import (
    complete_compensation,
    consume_approval,
    list_actions_for_workspace,
    propose_action,
    request_cancellation,
    resolve_replay_approval,
    submit_action_for_execution,
)
from doda.application.authz_service import (
    authorize_cancel_action,
    authorize_complete_compensation,
    authorize_consume_approval,
    authorize_propose_action,
)
from doda.domain.action.approval import Approval
from doda.domain.action.models import Action, ActionStatus
from doda.domain.action.tool_policy import describe_action_preview

router = APIRouter(tags=["actions"])


def _to_action_out(action: Action) -> ActionOut:
    return ActionOut(
        id=action.id,
        workspace_id=action.workspace_id,
        trace_id=action.trace_id,
        tool_name=action.tool_name,
        risk_level=action.risk_level,
        status=action.status,
        payload=action.payload,
        preview=describe_action_preview(action.tool_name, action.payload),
    )


def _to_approval_out(approval: Approval) -> ApprovalOut:
    return ApprovalOut(
        id=approval.id, status=approval.status, expires_at=approval.expires_at, nonce=approval.nonce
    )


async def _get_workspace_action(ctx: RequestContext, action_id: uuid.UUID) -> Action:
    """Every single-action endpoint in this file needs the same lookup:
    404 on a missing action OR one from a different workspace, before
    authorization even runs (10.1: don't reveal whether an action exists
    in a workspace the caller can't see) — same "404 before authorize"
    per-record tenancy guard test_cross_workspace_record_access.py checks
    for every other bitta-ID endpoint in the codebase."""
    action = await ctx.db.get(Action, action_id)
    if action is None or action.workspace_id != ctx.workspace.workspace_id:
        raise HTTPException(status_code=404, detail="action not found")
    return action


@router.post("/v1/workspaces/{workspace_id}/actions", response_model=SubmitActionResponse)
async def propose_and_submit_action(
    request: Request,
    body: ProposeActionRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    ctx: RequestContext = Depends(get_request_context),
) -> SubmitActionResponse:
    authorize_propose_action(ctx.workspace)
    actor_id = f"user:{ctx.workspace.user_id}"

    action, created = await propose_action(
        ctx.db,
        customer_id=ctx.workspace.customer_id,
        workspace_id=ctx.workspace.workspace_id,
        # TraceIdMiddleware already minted (or echoed) this request's
        # trace_id specifically so it can double as an Action's trace_id
        # (see middleware.py's docstring) — every audit event this action
        # ever produces is correlated to it. Generating a fresh, unrelated
        # uuid4() here (the previous behavior) silently broke that promise:
        # the HTTP response's X-Trace-Id and the Action's own trace_id (and
        # therefore every audit.*.v1 event about it) were two different,
        # uncorrelated UUIDs.
        trace_id=uuid.UUID(request.state.trace_id),
        actor_id=actor_id,
        tool_name=body.tool_name,
        risk_level=body.risk_level,
        payload=body.payload,
        idempotency_key=idempotency_key,
        task_id=body.task_id,
    )

    if created:
        action, approval = await submit_action_for_execution(ctx.db, action, actor_id=actor_id)
    else:
        # Idempotent replay (FR-ACT-004): the action already went through
        # its lifecycle on the first call — re-running validate_action would
        # attempt an illegal transition from its current (non-DRAFT) status.
        # Just hand back its current state, instead of re-processing it.
        # Whether the pending Approval's nonce may come along too is a
        # security decision, not a formatting one — see
        # action_service.resolve_replay_approval's own docstring (the
        # nonce is a one-time credential for the original proposer alone).
        approval = await resolve_replay_approval(ctx.db, action, actor_id=actor_id)

    return SubmitActionResponse(
        action=_to_action_out(action),
        approval=_to_approval_out(approval) if approval else None,
    )


@router.get("/v1/workspaces/{workspace_id}/actions/{action_id}", response_model=ActionOut)
async def get_action(action_id: uuid.UUID, ctx: RequestContext = Depends(get_request_context)) -> ActionOut:
    action = await _get_workspace_action(ctx, action_id)
    return _to_action_out(action)


@router.get("/v1/workspaces/{workspace_id}/actions", response_model=list[ActionOut])
async def list_workspace_actions(
    status: ActionStatus | None = None,
    limit: int = Query(default=50, le=200),
    ctx: RequestContext = Depends(get_request_context),
) -> list[ActionOut]:
    actions = await list_actions_for_workspace(
        ctx.db, workspace_id=ctx.workspace.workspace_id, status=status, limit=limit
    )
    return [_to_action_out(action) for action in actions]


@router.post("/v1/workspaces/{workspace_id}/approvals/{approval_id}/consume", response_model=ActionOut)
async def consume_action_approval(
    approval_id: uuid.UUID,
    body: ConsumeApprovalRequest,
    ctx: RequestContext = Depends(get_request_context),
) -> ActionOut:
    approval = await ctx.db.get(Approval, approval_id)
    if approval is None or approval.customer_id != ctx.workspace.customer_id:
        raise HTTPException(status_code=404, detail="approval not found")

    action = await _get_workspace_action(ctx, approval.action_id)
    authorize_consume_approval(ctx.workspace, action, auth_strength=ctx.auth_strength)
    action = await consume_approval(
        ctx.db,
        action,
        approval,
        approver_id=f"user:{ctx.workspace.user_id}",
        nonce=body.nonce,
    )
    return _to_action_out(action)


@router.post("/v1/workspaces/{workspace_id}/actions/{action_id}/cancel", response_model=ActionOut)
async def cancel_action(
    action_id: uuid.UUID, ctx: RequestContext = Depends(get_request_context)
) -> ActionOut:
    """FR-ACT-009: cancels a READY action outright, or requests a
    reversal (RUNNING -> COMPENSATING) for one already in flight — see
    action_service.request_cancellation's own docstring for why no other
    status is accepted."""
    action = await _get_workspace_action(ctx, action_id)
    authorize_cancel_action(ctx.workspace, action)
    action = await request_cancellation(ctx.db, action, actor_id=f"user:{ctx.workspace.user_id}")
    return _to_action_out(action)


@router.post(
    "/v1/workspaces/{workspace_id}/actions/{action_id}/compensate/complete", response_model=ActionOut
)
async def complete_action_compensation(
    action_id: uuid.UUID,
    body: CompleteCompensationRequest,
    ctx: RequestContext = Depends(get_request_context),
) -> ActionOut:
    """FR-ACT-009's other half — WorkspaceAdmin-only, since this is a
    human attesting a manual reversal happened (see action_service.
    complete_compensation's own docstring for why nothing here is
    verified automatically)."""
    action = await _get_workspace_action(ctx, action_id)
    authorize_complete_compensation(ctx.workspace)
    action = await complete_compensation(
        ctx.db, action, outcome=body.outcome, actor_id=f"user:{ctx.workspace.user_id}"
    )
    return _to_action_out(action)
