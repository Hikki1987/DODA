"""Workspace membership + lifecycle endpoints — FR-WKS-005/006. Customer
creation (FR-WKS-001) is deliberately not here or anywhere in api/ — see
doda.application.customer_service's module docstring: public self-serve
signup is out of scope for v1 (2.3)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from doda.api.dependencies import (
    RequestContext,
    get_request_context,
    get_request_context_allow_archived,
)
from doda.api.workspace_admin_schemas import (
    AddWorkspaceMemberRequest,
    ChangeWorkspaceMemberRoleRequest,
    WorkspaceMembershipOut,
    WorkspaceOut,
)
from doda.application.authz_service import authorize_archive_workspace, authorize_manage_workspace_members
from doda.application.workspace_service import (
    add_workspace_member,
    archive_workspace,
    change_workspace_member_role,
    remove_workspace_member,
    restore_workspace,
)
from doda.domain.customer.models import CustomerMembership
from doda.domain.workspace.models import Workspace, WorkspaceMembership

router = APIRouter(tags=["workspace-admin"])


def _to_membership_out(membership: WorkspaceMembership) -> WorkspaceMembershipOut:
    return WorkspaceMembershipOut(
        id=membership.id,
        customer_membership_id=membership.customer_membership_id,
        workspace_id=membership.workspace_id,
        role=membership.role,
    )


def _to_workspace_out(workspace: Workspace) -> WorkspaceOut:
    return WorkspaceOut(
        id=workspace.id, customer_id=workspace.customer_id, name=workspace.name, archived_at=workspace.archived_at
    )


async def _get_current_workspace(ctx: RequestContext) -> Workspace:
    workspace = await ctx.db.get(Workspace, ctx.workspace.workspace_id)
    assert workspace is not None  # get_request_context already proved this row exists
    return workspace


@router.post("/v1/workspaces/{workspace_id}/members", response_model=WorkspaceMembershipOut)
async def add_member(
    body: AddWorkspaceMemberRequest, ctx: RequestContext = Depends(get_request_context)
) -> WorkspaceMembershipOut:
    authorize_manage_workspace_members(ctx.workspace)

    customer_membership = await ctx.db.get(CustomerMembership, body.customer_membership_id)
    if customer_membership is None:
        # RLS already hides a different customer's row as "not found" —
        # same DENY-shaped 404 as everywhere else in this API (10.1).
        raise HTTPException(status_code=404, detail="customer membership not found")

    workspace = await _get_current_workspace(ctx)
    membership = await add_workspace_member(
        ctx.db,
        workspace=workspace,
        customer_membership=customer_membership,
        role=body.role.value,
        actor_id=f"user:{ctx.workspace.user_id}",
    )
    return _to_membership_out(membership)


async def _get_workspace_membership(ctx: RequestContext, membership_id: uuid.UUID) -> WorkspaceMembership:
    membership = await ctx.db.get(WorkspaceMembership, membership_id)
    if membership is None or membership.workspace_id != ctx.workspace.workspace_id:
        raise HTTPException(status_code=404, detail="workspace membership not found")
    return membership


@router.patch(
    "/v1/workspaces/{workspace_id}/members/{membership_id}", response_model=WorkspaceMembershipOut
)
async def change_member_role(
    membership_id: uuid.UUID,
    body: ChangeWorkspaceMemberRoleRequest,
    ctx: RequestContext = Depends(get_request_context),
) -> WorkspaceMembershipOut:
    authorize_manage_workspace_members(ctx.workspace)
    membership = await _get_workspace_membership(ctx, membership_id)
    membership = await change_workspace_member_role(
        ctx.db, membership, new_role=body.role.value, actor_id=f"user:{ctx.workspace.user_id}"
    )
    return _to_membership_out(membership)


@router.delete("/v1/workspaces/{workspace_id}/members/{membership_id}", status_code=204)
async def remove_member(
    membership_id: uuid.UUID, ctx: RequestContext = Depends(get_request_context)
) -> None:
    authorize_manage_workspace_members(ctx.workspace)
    membership = await _get_workspace_membership(ctx, membership_id)
    await remove_workspace_member(ctx.db, membership, actor_id=f"user:{ctx.workspace.user_id}")


@router.post("/v1/workspaces/{workspace_id}/archive", response_model=WorkspaceOut)
async def archive_current_workspace(ctx: RequestContext = Depends(get_request_context)) -> WorkspaceOut:
    authorize_archive_workspace(ctx.workspace)
    workspace = await _get_current_workspace(ctx)
    workspace = await archive_workspace(ctx.db, workspace, actor_id=f"user:{ctx.workspace.user_id}")
    return _to_workspace_out(workspace)


@router.post("/v1/workspaces/{workspace_id}/restore", response_model=WorkspaceOut)
async def restore_current_workspace(
    ctx: RequestContext = Depends(get_request_context_allow_archived),
) -> WorkspaceOut:
    authorize_archive_workspace(ctx.workspace)
    workspace = await _get_current_workspace(ctx)
    workspace = await restore_workspace(ctx.db, workspace, actor_id=f"user:{ctx.workspace.user_id}")
    return _to_workspace_out(workspace)
