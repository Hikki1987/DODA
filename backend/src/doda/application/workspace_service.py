"""Workspace creation — FR-WKS-002. Deliberately minimal: this session's
scope is the S1/S2 slice (actions, approvals, the authz bootstrap), not the
full FR-WKS surface (invite/remove members, archive/restore, settings —
still open work). Exists here only because creating a Workspace and its
WorkspaceTenantIndex row must be atomic (same transaction), and that
invariant belongs in application code, not scattered across callers/tests.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from doda.domain.workspace.models import Workspace, WorkspaceTenantIndex


async def create_workspace(session: AsyncSession, *, customer_id: uuid.UUID, name: str) -> Workspace:
    workspace = Workspace(customer_id=customer_id, name=name)
    session.add(workspace)
    await session.flush()
    session.add(WorkspaceTenantIndex(workspace_id=workspace.id, customer_id=customer_id))
    await session.flush()
    return workspace
