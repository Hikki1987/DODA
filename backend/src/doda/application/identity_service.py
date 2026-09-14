"""Identity — FR-AUTH-001. `get_or_create_user` is the one place a `User`
row is minted outside test/seed scripts: every real login (currently just
Google, see `oidc_login_service.py`) resolves to this same function, so a
second provider later reuses it rather than growing its own copy.
"""

import hashlib

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from doda.domain.identity.models import User


def hash_oidc_subject(*, provider: str, subject: str) -> str:
    """Stable hash binding provider+subject. Never store the raw provider
    subject claim (see User.oidc_subject_hash's own docstring) — the
    provider prefix keeps two providers that happened to issue the same
    subject string from colliding on the same User row."""
    return hashlib.sha256(f"{provider}:{subject}".encode()).hexdigest()


async def get_or_create_user(session: AsyncSession, *, oidc_subject_hash: str, display_name: str) -> User:
    """Idempotent: a returning login resolves to the same User row. Races
    (two concurrent first-logins for the same subject) are handled the
    same way as `kill_switch_service`'s engage functions — an insert race
    where both callers want the same outcome (a User existing for this
    subject), not a business error like `invite_customer_member`'s
    duplicate-invite case — so the loser re-reads and returns the row the
    winner created instead of raising."""
    existing = await session.scalar(select(User).where(User.oidc_subject_hash == oidc_subject_hash))
    if existing is not None:
        return existing

    try:
        async with session.begin_nested():
            user = User(oidc_subject_hash=oidc_subject_hash, display_name=display_name)
            session.add(user)
            await session.flush()
    except IntegrityError:
        winner = await session.scalar(select(User).where(User.oidc_subject_hash == oidc_subject_hash))
        if winner is None:  # pragma: no cover — defensive: see module docstring
            raise
        return winner
    return user
