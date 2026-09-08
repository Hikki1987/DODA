"""Who am I, what do I have access to" — session-scoped, not workspace-
or customer-scoped, matching api/sessions.py's pattern. Every other
endpoint in this API requires the caller to already know a workspace_id or
customer_id up front; this is the one entry point a client can call right
after login with nothing but a session.
"""

from fastapi import APIRouter, Depends

from doda.api.dependencies import CurrentIdentity, get_current_identity
from doda.api.me_schemas import MyWorkspaceOut
from doda.application.workspace_service import list_my_workspaces

router = APIRouter(tags=["me"])


@router.get("/v1/me/workspaces", response_model=list[MyWorkspaceOut])
async def list_my_workspaces_endpoint(
    identity: CurrentIdentity = Depends(get_current_identity),
) -> list[MyWorkspaceOut]:
    entries = await list_my_workspaces(identity.user_id)
    return [
        MyWorkspaceOut(
            customer_id=entry.customer_id,
            customer_name=entry.customer_name,
            workspace_id=entry.workspace_id,
            workspace_name=entry.workspace_name,
            role=entry.role,
        )
        for entry in entries
    ]
