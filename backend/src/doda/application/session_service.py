"""Session lifecycle — FR-AUTH-003/005/006.

`create_session` is called both by the real Google OIDC login callback
(`doda.application.oidc_login_service`, FR-AUTH-001) and by a dev/test
seam used directly by tests and seed scripts, which never have a real
HTTP request to pull a user_agent from — that path passes none, and
`is_new_device_login` (FR-AUTH-007) treats "no user_agent" as "no
evidence", never as anomalous. Everything downstream of session
creation — idle/absolute timeout enforcement, revoke — is the real
thing either way, not a stub.
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
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    auth_strength: AuthStrength,
    user_agent: str | None = None,
) -> Session:
    now = utcnow()
    record = Session(
        user_id=user_id,
        auth_strength=auth_strength,
        last_seen_at=now,
        expires_at=now + ABSOLUTE_TIMEOUT,
        user_agent=user_agent,
    )
    session.add(record)
    await session.flush()
    return record


async def is_new_device_login(session: AsyncSession, *, user_id: uuid.UUID, user_agent: str) -> bool:
    """FR-AUTH-007: true iff this exact user_agent has never appeared on
    any of this user's PRIOR sessions, AND the user has at least one
    prior session whose user_agent is known. A first-ever login (or a
    user whose only prior sessions predate this column / came through the
    dev/test seam) has no baseline to compare against, so it is never
    itself flagged — there is nothing anomalous about the first device
    you're ever seen on. Must be called BEFORE create_session persists
    the new row, or that row would count as its own baseline.

    Known limitation (found in the 8th security-review pass, judged a
    monitoring-detection gap rather than an authorization vulnerability
    — nothing in this codebase's authz chain depends on this check, and
    the attacker precondition it needs is an out-of-band account
    takeover this codebase cannot see either way): a caller's request
    that carries no User-Agent header at all makes the OIDC callback
    pass user_agent=None here, which this function's own "no baseline"
    rule then treats identically to a first-ever login — silently
    skipping the anomaly check rather than flagging the missing header
    itself as suspicious. Real browsers always send a User-Agent, so
    this only matters for a scripted client completing the OAuth
    exchange directly."""
    prior_agents = (
        (
            await session.execute(
                select(Session.user_agent).where(Session.user_id == user_id, Session.user_agent.is_not(None))
            )
        )
        .scalars()
        .all()
    )
    if not prior_agents:
        return False
    return user_agent not in prior_agents


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
