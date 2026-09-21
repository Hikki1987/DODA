"""Session self-service — FR-CTL-001 ("Faol sessiya... ko'rinishi") and
FR-CTL-002 ("Sessiya revoke"). Not workspace-scoped — a session belongs to
a user, not a tenant — so this uses get_current_identity rather than
get_request_context.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from doda.api.dependencies import CurrentIdentity, get_current_identity
from doda.api.session_schemas import SessionOut
from doda.application.session_service import list_active_sessions_for_user, revoke_session
from doda.db import async_session_factory
from doda.domain.identity.models import Session as SessionModel

router = APIRouter(tags=["sessions"])


def _to_out(session: SessionModel, *, current_session_id: uuid.UUID) -> SessionOut:
    return SessionOut(
        id=session.id,
        created_at=session.created_at,
        last_seen_at=session.last_seen_at,
        expires_at=session.expires_at,
        auth_strength=session.auth_strength,
        is_current=session.id == current_session_id,
    )


@router.get("/v1/sessions", response_model=list[SessionOut])
async def list_my_sessions(identity: CurrentIdentity = Depends(get_current_identity)) -> list[SessionOut]:
    async with async_session_factory() as db:
        sessions = await list_active_sessions_for_user(db, identity.user_id)
    return [_to_out(s, current_session_id=identity.session_id) for s in sessions]


@router.delete("/v1/sessions/{session_id}", status_code=204)
async def revoke_my_session(
    session_id: uuid.UUID, identity: CurrentIdentity = Depends(get_current_identity)
) -> None:
    async with async_session_factory() as db:
        target = await db.get(SessionModel, session_id)
        if target is None or target.user_id != identity.user_id:
            # Not-found, not denied: another user's session id existing at
            # all is not something to confirm (10.1).
            raise HTTPException(status_code=404, detail="session not found")
        await revoke_session(db, session_id)
        await db.commit()
