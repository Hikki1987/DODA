"""Audit viewer query — FR-AUD-002. Read-only; scoping (who may see what)
is enforced by callers via authz_service, not here — this module just
knows how to filter and paginate.
"""

import uuid

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from doda.domain.audit.models import AuditEvent

MAX_PAGE_SIZE = 200


async def list_audit_events(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
    actor_id: str | None = None,
    event_type: str | None = None,
    trace_id: uuid.UUID | None = None,
    limit: int = 50,
    before_id: uuid.UUID | None = None,
) -> list[AuditEvent]:
    """Cursor-paginated (11.2: "Pagination cursor asosida"): `before_id` is
    the id of the last event from a previous page — this page returns
    events strictly older than it. Ordered newest-first.
    """
    limit = min(limit, MAX_PAGE_SIZE)
    query = select(AuditEvent).where(AuditEvent.customer_id == customer_id)

    if workspace_id is not None:
        query = query.where(AuditEvent.workspace_id == workspace_id)
    if actor_id is not None:
        query = query.where(AuditEvent.actor_id == actor_id)
    if event_type is not None:
        query = query.where(AuditEvent.event_type == event_type)
    if trace_id is not None:
        query = query.where(AuditEvent.trace_id == trace_id)

    if before_id is not None:
        cursor_row = await session.get(AuditEvent, before_id)
        if cursor_row is not None:
            query = query.where(
                tuple_(AuditEvent.created_at, AuditEvent.id)
                < tuple_(cursor_row.created_at, cursor_row.id)
            )

    query = query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit)
    result = await session.execute(query)
    return list(result.scalars())
