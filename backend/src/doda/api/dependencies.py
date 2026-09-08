"""FastAPI dependencies implementing the authoritative chain (section 10):
Authentication Session -> [tenant bootstrap] -> Workspace Membership ->
RBAC. No route handler may accept customer_id, or a tenant-scoping
workspace_id, as a client-supplied body/query value that bypasses this
chain — workspace_id is the one exception, taken from the URL path, because
resolving *which* workspace the caller means is exactly what this chain is
for; it is never trusted as *proof* of membership.

KNOWN LIMITATION: `Authorization: Bearer <session-id>` is a raw session
UUID, not a signed token — there is no OIDC/JWT layer yet (FR-AUTH-001 is
S3 scope). This is sufficient to prove "holds a valid, unexpired,
unrevoked Session row" (real DB-backed check, not a stub) but is not
production-grade bearer token handling (no signature, no rotation).
"""

import dataclasses
import uuid
from collections.abc import AsyncGenerator

from fastapi import Header, Path
from sqlalchemy.ext.asyncio import AsyncSession

from doda.application.authz_service import (
    AuthorizationError,
    WorkspaceContext,
    get_workspace_context,
)
from doda.application.session_service import SessionInvalidError, resolve_session
from doda.db import async_session_factory, tenant_scoped_session
from doda.domain.identity.models import AuthStrength
from doda.domain.security.decisions import Decision
from doda.domain.workspace.models import WorkspaceTenantIndex


def _parse_bearer_session_id(authorization: str | None) -> uuid.UUID:
    if not authorization or not authorization.startswith("Bearer "):
        raise SessionInvalidError("missing bearer session token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return uuid.UUID(token)
    except ValueError:
        raise SessionInvalidError("malformed session token") from None


@dataclasses.dataclass(frozen=True)
class RequestContext:
    workspace: WorkspaceContext
    auth_strength: AuthStrength
    db: AsyncSession


async def _resolve_request_context(
    *, workspace_id: uuid.UUID, authorization: str | None, allow_archived: bool
) -> AsyncGenerator[RequestContext, None]:
    session_id = _parse_bearer_session_id(authorization)

    async with async_session_factory() as base_session:
        session_record = await resolve_session(base_session, session_id)
        index_row = await base_session.get(WorkspaceTenantIndex, workspace_id)

    if index_row is None:
        # Same DENY as "membership not found" — see get_workspace_context's
        # docstring: existence of a workspace id is not something to leak.
        raise AuthorizationError(Decision.DENY, "workspace not found")

    async with tenant_scoped_session(index_row.customer_id) as db:
        context = await get_workspace_context(
            db, user_id=session_record.user_id, workspace_id=workspace_id, allow_archived=allow_archived
        )
        yield RequestContext(workspace=context, auth_strength=session_record.auth_strength, db=db)


async def get_request_context(
    workspace_id: uuid.UUID = Path(...),
    authorization: str | None = Header(default=None),
) -> AsyncGenerator[RequestContext, None]:
    async for ctx in _resolve_request_context(
        workspace_id=workspace_id, authorization=authorization, allow_archived=False
    ):
        yield ctx


async def get_request_context_allow_archived(
    workspace_id: uuid.UUID = Path(...),
    authorization: str | None = Header(default=None),
) -> AsyncGenerator[RequestContext, None]:
    """Only for the workspace-restore endpoint (FR-WKS-006) — see
    get_workspace_context's `allow_archived` docstring. Never use this for
    any other route."""
    async for ctx in _resolve_request_context(
        workspace_id=workspace_id, authorization=authorization, allow_archived=True
    ):
        yield ctx
