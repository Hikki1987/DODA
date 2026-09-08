"""Audit viewer — FR-AUD-002. Two endpoints matching 10.2's "Audit ko'rish"
row exactly: workspace-scoped (Member = own actions only, WorkspaceAdmin =
whole workspace) and customer-scoped (CustomerOwner / Auditor = whole
customer). Every read here also writes an "audit.viewed.v1" audit event
itself (FR-AUD-002 acceptance: "eksport audit qilinadi") — capturing who
queried what filter and how many rows came back, never the viewed events'
own content, so viewing the audit log doesn't quietly duplicate its
content into a new entry.
"""

import uuid

from fastapi import APIRouter, Depends, Query

from doda.api.audit_schemas import AuditEventOut
from doda.api.dependencies import (
    CustomerRequestContext,
    RequestContext,
    get_customer_request_context,
    get_request_context,
)
from doda.application.audit_query_service import list_audit_events
from doda.application.audit_service import record_audit_event
from doda.application.authz_service import authorize_view_customer_audit
from doda.domain.audit.models import AuditEvent
from doda.domain.security.roles import WorkspaceRole

router = APIRouter(tags=["audit"])


def _to_out(event: AuditEvent) -> AuditEventOut:
    return AuditEventOut(
        id=event.id,
        customer_id=event.customer_id,
        workspace_id=event.workspace_id,
        trace_id=event.trace_id,
        actor_id=event.actor_id,
        event_type=event.event_type,
        occurred_at=event.occurred_at,
        safe_metadata=event.safe_metadata,
        prev_hash=event.prev_hash,
        hash=event.hash,
    )


@router.get("/v1/workspaces/{workspace_id}/audit", response_model=list[AuditEventOut])
async def list_workspace_audit(
    event_type: str | None = None,
    trace_id: uuid.UUID | None = None,
    limit: int = Query(default=50, le=200),
    before_id: uuid.UUID | None = None,
    ctx: RequestContext = Depends(get_request_context),
) -> list[AuditEventOut]:
    actor_filter = None
    if ctx.workspace.role is WorkspaceRole.MEMBER:
        # 10.2: Member sees "O'z amallarini" only — WorkspaceAdmin has no
        # such restriction and sees the whole workspace.
        actor_filter = f"user:{ctx.workspace.user_id}"

    events = await list_audit_events(
        ctx.db,
        customer_id=ctx.workspace.customer_id,
        workspace_id=ctx.workspace.workspace_id,
        actor_id=actor_filter,
        event_type=event_type,
        trace_id=trace_id,
        limit=limit,
        before_id=before_id,
    )

    await record_audit_event(
        ctx.db,
        customer_id=ctx.workspace.customer_id,
        workspace_id=ctx.workspace.workspace_id,
        trace_id=uuid.uuid4(),
        actor_id=f"user:{ctx.workspace.user_id}",
        event_type="audit.viewed.v1",
        safe_metadata={"scope": "workspace", "result_count": len(events), "event_type_filter": event_type},
    )
    return [_to_out(e) for e in events]


@router.get("/v1/customers/{customer_id}/audit", response_model=list[AuditEventOut])
async def list_customer_audit(
    event_type: str | None = None,
    trace_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    limit: int = Query(default=50, le=200),
    before_id: uuid.UUID | None = None,
    ctx: CustomerRequestContext = Depends(get_customer_request_context),
) -> list[AuditEventOut]:
    authorize_view_customer_audit(ctx.customer)

    events = await list_audit_events(
        ctx.db,
        customer_id=ctx.customer.customer_id,
        workspace_id=workspace_id,
        event_type=event_type,
        trace_id=trace_id,
        limit=limit,
        before_id=before_id,
    )

    await record_audit_event(
        ctx.db,
        customer_id=ctx.customer.customer_id,
        trace_id=uuid.uuid4(),
        actor_id=f"user:{ctx.customer.user_id}",
        event_type="audit.viewed.v1",
        safe_metadata={
            "scope": "customer",
            "role": ctx.customer.role.value,
            "result_count": len(events),
            "event_type_filter": event_type,
        },
    )
    return [_to_out(e) for e in events]
