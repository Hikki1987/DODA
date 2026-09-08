"""Kill switch endpoints — FR-CTL-003. Two independent scopes, each with
its own authz gate (10.2): workspace (workspace_admin) and customer
(customer_owner). No global/platform scope — see
doda.domain.security.kill_switch's module docstring for why."""

from fastapi import APIRouter, Depends

from doda.api.dependencies import (
    CustomerRequestContext,
    RequestContext,
    get_customer_request_context,
    get_request_context,
)
from doda.api.kill_switch_schemas import EngageKillSwitchRequest, KillSwitchStatusOut
from doda.application.authz_service import (
    authorize_engage_customer_kill_switch,
    authorize_engage_workspace_kill_switch,
)
from doda.application.kill_switch_service import (
    disengage_customer_kill_switch,
    disengage_workspace_kill_switch,
    engage_customer_kill_switch,
    engage_workspace_kill_switch,
)

router = APIRouter(tags=["kill-switch"])


@router.post("/v1/workspaces/{workspace_id}/kill-switch/engage", response_model=KillSwitchStatusOut)
async def engage_workspace(
    body: EngageKillSwitchRequest, ctx: RequestContext = Depends(get_request_context)
) -> KillSwitchStatusOut:
    authorize_engage_workspace_kill_switch(ctx.workspace)
    await engage_workspace_kill_switch(
        ctx.db,
        workspace_id=ctx.workspace.workspace_id,
        customer_id=ctx.workspace.customer_id,
        actor_id=f"user:{ctx.workspace.user_id}",
        reason=body.reason,
    )
    return KillSwitchStatusOut(engaged=True)


@router.post("/v1/workspaces/{workspace_id}/kill-switch/disengage", response_model=KillSwitchStatusOut)
async def disengage_workspace(ctx: RequestContext = Depends(get_request_context)) -> KillSwitchStatusOut:
    authorize_engage_workspace_kill_switch(ctx.workspace)
    await disengage_workspace_kill_switch(
        ctx.db,
        workspace_id=ctx.workspace.workspace_id,
        customer_id=ctx.workspace.customer_id,
        actor_id=f"user:{ctx.workspace.user_id}",
    )
    return KillSwitchStatusOut(engaged=False)


@router.post("/v1/customers/{customer_id}/kill-switch/engage", response_model=KillSwitchStatusOut)
async def engage_customer(
    body: EngageKillSwitchRequest, ctx: CustomerRequestContext = Depends(get_customer_request_context)
) -> KillSwitchStatusOut:
    authorize_engage_customer_kill_switch(ctx.customer)
    await engage_customer_kill_switch(
        ctx.db,
        customer_id=ctx.customer.customer_id,
        actor_id=f"user:{ctx.customer.user_id}",
        reason=body.reason,
    )
    return KillSwitchStatusOut(engaged=True)


@router.post("/v1/customers/{customer_id}/kill-switch/disengage", response_model=KillSwitchStatusOut)
async def disengage_customer(
    ctx: CustomerRequestContext = Depends(get_customer_request_context),
) -> KillSwitchStatusOut:
    authorize_engage_customer_kill_switch(ctx.customer)
    await disengage_customer_kill_switch(
        ctx.db, customer_id=ctx.customer.customer_id, actor_id=f"user:{ctx.customer.user_id}"
    )
    return KillSwitchStatusOut(engaged=False)
