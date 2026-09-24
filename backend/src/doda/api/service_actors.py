"""FR-AUTH-009's credential-management endpoints — minting, listing, and
revoking a Service Actor's machine credential. The actual authentication
endpoint (exchanging a secret for a Session) lives in api/auth.py
alongside the other "no session exists yet" routes; this router is
CustomerOwner-scoped like api/customer_admin.py.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from doda.api.dependencies import CustomerRequestContext, get_customer_request_context
from doda.api.service_actor_schemas import (
    CreateServiceActorRequest,
    ServiceActorCredentialCreatedOut,
    ServiceActorCredentialOut,
)
from doda.application.authz_service import authorize_manage_service_actors
from doda.application.service_actor_service import (
    create_service_actor_credential,
    list_service_actor_credentials,
    revoke_service_actor_credential,
)
from doda.domain.identity.models import ServiceActorCredential

router = APIRouter(tags=["service-actors"])


def _to_out(record: ServiceActorCredential) -> ServiceActorCredentialOut:
    return ServiceActorCredentialOut(
        id=record.id, name=record.name, created_at=record.created_at, revoked_at=record.revoked_at
    )


@router.post("/v1/customers/{customer_id}/service-actors", response_model=ServiceActorCredentialCreatedOut)
async def create_service_actor(
    body: CreateServiceActorRequest,
    ctx: CustomerRequestContext = Depends(get_customer_request_context),
) -> ServiceActorCredentialCreatedOut:
    authorize_manage_service_actors(ctx.customer)
    record, secret = await create_service_actor_credential(
        ctx.db, customer_id=ctx.customer.customer_id, name=body.name, created_by=ctx.customer.user_id
    )
    return ServiceActorCredentialCreatedOut(**_to_out(record).model_dump(), secret=secret)


@router.get("/v1/customers/{customer_id}/service-actors", response_model=list[ServiceActorCredentialOut])
async def list_service_actors(
    ctx: CustomerRequestContext = Depends(get_customer_request_context),
) -> list[ServiceActorCredentialOut]:
    authorize_manage_service_actors(ctx.customer)
    records = await list_service_actor_credentials(ctx.db, customer_id=ctx.customer.customer_id)
    return [_to_out(record) for record in records]


@router.delete("/v1/customers/{customer_id}/service-actors/{credential_id}", status_code=204)
async def revoke_service_actor(
    credential_id: uuid.UUID,
    ctx: CustomerRequestContext = Depends(get_customer_request_context),
) -> None:
    authorize_manage_service_actors(ctx.customer)
    record = await revoke_service_actor_credential(
        ctx.db,
        customer_id=ctx.customer.customer_id,
        credential_id=credential_id,
        actor_id=f"user:{ctx.customer.user_id}",
    )
    if record is None:
        raise HTTPException(status_code=404, detail="service actor credential not found")
