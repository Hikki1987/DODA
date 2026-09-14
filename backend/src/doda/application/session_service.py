"""Session lifecycle — FR-AUTH-003/005/006.

KNOWN LIMITATION: `create_session` is a dev/test seam standing in for the
real OIDC login callback (FR-AUTH-001), which belongs to S3 (Web product
shell) and requires an actual external provider. Everything downstream of
session creation here — idle/absolute timeout enforcement, revoke — is the
real thing, not a stub.
"""

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doda.domain.base import utcnow
from doda.domain.identity.models import AuthStrength, Session

IDLE_TIMEOUT = timedelta(minutes=30)
ABSOLUTE_TIMEOUT = timedelta(hours=12)


class SessionInvalidError(Exception):
    """Raised for any reason a session must not be trusted: not found,
    revoked, idle-timed-out, or past its absolute expiry. Deliberately one
    exception type — the caller (API layer) always responds 401 regardless
    of which reason applied, so as not to help an attacker distinguish
    "no such session" from "expired session" (10.1: sezgir tafsilot
    ko'rsatilmaydi)."""


async def create_session(
    session: AsyncSession, *, user_id: uuid.UUID, auth_strength: AuthStrength
) -> Session:
    now = utcnow()
    record = Session(
        user_id=user_id,
        auth_strength=auth_strength,
        last_seen_at=now,
        expires_at=now + ABSOLUTE_TIMEOUT,
    )
    session.add(record)
    await session.flush()
    return record


async def resolve_session(session: AsyncSession, session_id: uuid.UUID) -> Session:
    """Validate and touch a session (updates last_seen_at), or raise
    SessionInvalidError. Must be called on every authenticated request."""
    record = await session.get(Session, session_id)
    now = utcnow()

    if record is None:
        raise SessionInvalidError("no such session")
    if record.revoked_at is not None:
        raise SessionInvalidError("session revoked")
    if now > record.expires_at:
        raise SessionInvalidError("session past absolute timeout")
    if now - record.last_seen_at > IDLE_TIMEOUT:
        raise SessionInvalidError("session idle timeout")

    record.last_seen_at = now
    await session.flush()
    return record


async def list_active_sessions_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[Session]:
    """FR-CTL-001: 'Faol sessiya... ko'rinishi.' Same liveness definition as
    resolve_session (not revoked, not past absolute expiry, not idle-timed-
    out) but read-only — listing must never itself touch last_seen_at, or
    just looking at your session list would silently keep every one of them
    alive forever."""
    now = utcnow()
    result = await session.execute(
        select(Session)
        .where(
            Session.user_id == user_id,
            Session.revoked_at.is_(None),
            Session.expires_at > now,
            Session.last_seen_at > now - IDLE_TIMEOUT,
        )
        .order_by(Session.last_seen_at.desc())
    )
    return list(result.scalars())


async def revoke_session(session: AsyncSession, session_id: uuid.UUID) -> None:
    """FR-AUTH-005: remote revoke. Idempotent — revoking twice is a no-op,
    not an error, since the caller's goal ("this session must not work") is
    already satisfied."""
    record = await session.get(Session, session_id)
    if record is not None and record.revoked_at is None:
        record.revoked_at = utcnow()
        await session.flush()
