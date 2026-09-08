"""Customer membership endpoints — FR-WKS-005. Customer creation (FR-WKS-001)
stays out of api/ (2.3: public self-serve signup is out of scope for v1),
but membership management within an EXISTING customer — invite, re-role,
remove — is in-scope and was, until now, only an application-layer
function (customer_service.invite_customer_member) with no HTTP surface.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from doda.api.customer_admin_schemas import (
    ChangeCustomerMemberRoleRequest,
    CustomerMembershipOut,
    InviteCustomerMemberRequest,
)
from doda.api.dependencies import CustomerRequestContext, get_customer_request_context
from doda.application.authz_service import authorize_manage_customer_members
from doda.application.customer_service import (
    change_customer_member_role,
    invite_customer_member,
    remove_customer_member,
)
from doda.domain.customer.models import CustomerMembership
from doda.domain.identity.models import User

router = APIRouter(tags=["customer-admin"])


def _to_membership_out(membership: CustomerMembership) -> CustomerMembershipOut:
    return CustomerMembershipOut(
        id=membership.id,
        customer_id=membership.customer_id,
        user_id=membership.user_id,
        role=membership.role,
    )


@router.post("/v1/customers/{customer_id}/members", response_model=CustomerMembershipOut)
async def invite_member(
    body: InviteCustomerMemberRequest,
    ctx: CustomerRequestContext = Depends(get_customer_request_context),
) -> CustomerMembershipOut:
    authorize_manage_customer_members(ctx.customer)

    # Identity has no RLS/FK tie to CustomerMembership (6.2: no cross-domain
    # FK, ID-reference only), so an unchecked user_id would silently create
    # a membership for nobody — same "does the referenced row exist" check
    # api/workspace_admin.py's add_member already does for its own input.
    invitee = await ctx.db.get(User, body.user_id)
    if invitee is None:
        raise HTTPException(status_code=404, detail="user not found")

    membership = await invite_customer_member(
        ctx.db,
        customer_id=ctx.customer.customer_id,
        user_id=body.user_id,
        role=body.role,
        actor_id=f"user:{ctx.customer.user_id}",
    )
    return _to_membership_out(membership)


async def _get_customer_membership(
    ctx: CustomerRequestContext, membership_id: uuid.UUID
) -> CustomerMembership:
    membership = await ctx.db.get(CustomerMembership, membership_id)
    if membership is None or membership.customer_id != ctx.customer.customer_id:
        raise HTTPException(status_code=404, detail="customer membership not found")
    return membership


@router.patch("/v1/customers/{customer_id}/members/{membership_id}", response_model=CustomerMembershipOut)
async def change_member_role(
    membership_id: uuid.UUID,
    body: ChangeCustomerMemberRoleRequest,
    ctx: CustomerRequestContext = Depends(get_customer_request_context),
) -> CustomerMembershipOut:
    authorize_manage_customer_members(ctx.customer)
    membership = await _get_customer_membership(ctx, membership_id)
    membership = await change_customer_member_role(
        ctx.db, membership, new_role=body.role, actor_id=f"user:{ctx.customer.user_id}"
    )
    return _to_membership_out(membership)


@router.delete("/v1/customers/{customer_id}/members/{membership_id}", status_code=204)
async def remove_member(
    membership_id: uuid.UUID, ctx: CustomerRequestContext = Depends(get_customer_request_context)
) -> None:
    authorize_manage_customer_members(ctx.customer)
    membership = await _get_customer_membership(ctx, membership_id)
    await remove_customer_member(ctx.db, membership, actor_id=f"user:{ctx.customer.user_id}")
