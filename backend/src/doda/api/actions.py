"""Action endpoints — Experience layer (6.1). Every handler receives its
tenant/authz context only via RequestContext (doda.api.dependencies); none
accepts customer_id or actor_id from the client, per CLAUDE.md's dependency
rules and the master instruction.
"""

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select

from doda.api.dependencies import RequestContext, get_request_context
from doda.api.schemas import (
    ActionOut,
    ApprovalOut,
    ConsumeApprovalRequest,
    ProposeActionRequest,
    SubmitActionResponse,
)
from doda.application.action_service import (
    consume_approval,
    propose_action,
    submit_action_for_execution,
)
from doda.application.authz_service import authorize_consume_approval, authorize_propose_action
from doda.domain.action.approval import Approval
from doda.domain.action.models import Action, ActionStatus

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
    )


def _to_approval_out(approval: Approval) -> ApprovalOut:
    return ApprovalOut(
        id=approval.id, status=approval.status, expires_at=approval.expires_at, nonce=approval.nonce
    )


@router.post("/v1/workspaces/{workspace_id}/actions", response_model=SubmitActionResponse)
async def propose_and_submit_action(
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
        trace_id=uuid.uuid4(),
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
        # Just hand back its current state, including any still-pending
        # approval, instead of re-processing it.
        approval = None
        if action.status is ActionStatus.AWAITING_APPROVAL:
            approval = await ctx.db.scalar(
                select(Approval)
                .where(Approval.action_id == action.id)
                .order_by(Approval.created_at.desc())
                .limit(1)
            )

    return SubmitActionResponse(
        action=_to_action_out(action),
        approval=_to_approval_out(approval) if approval else None,
    )


@router.get("/v1/workspaces/{workspace_id}/actions/{action_id}", response_model=ActionOut)
async def get_action(
    action_id: uuid.UUID, ctx: RequestContext = Depends(get_request_context)
) -> ActionOut:
    action = await ctx.db.get(Action, action_id)
    if action is None or action.workspace_id != ctx.workspace.workspace_id:
        raise HTTPException(status_code=404, detail="action not found")
    return _to_action_out(action)


@router.post(
    "/v1/workspaces/{workspace_id}/approvals/{approval_id}/consume", response_model=ActionOut
)
async def consume_action_approval(
    approval_id: uuid.UUID,
    body: ConsumeApprovalRequest,
    ctx: RequestContext = Depends(get_request_context),
) -> ActionOut:
    approval = await ctx.db.get(Approval, approval_id)
    if approval is None or approval.customer_id != ctx.workspace.customer_id:
        raise HTTPException(status_code=404, detail="approval not found")

    action = await ctx.db.get(Action, approval.action_id)
    if action is None or action.workspace_id != ctx.workspace.workspace_id:
        raise HTTPException(status_code=404, detail="action not found")

    authorize_consume_approval(ctx.workspace, action, auth_strength=ctx.auth_strength)
    action = await consume_approval(
        ctx.db,
        action,
        approval,
        approver_id=f"user:{ctx.workspace.user_id}",
        nonce=body.nonce,
    )
    return _to_action_out(action)
