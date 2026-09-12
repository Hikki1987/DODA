"""Real-DB tests for get_or_create_user — FR-AUTH-001. Pure-function
hashing tests live in tests/unit/test_identity_service.py.
"""

import asyncio
import uuid

from sqlalchemy import select

from doda.application.identity_service import get_or_create_user, hash_oidc_subject
from doda.db import async_session_factory
from doda.domain.identity.models import User


async def test_repeated_login_resolves_to_the_same_user(db_available: bool) -> None:
    subject_hash = hash_oidc_subject(provider="google", subject=str(uuid.uuid4()))

    async with async_session_factory() as db:
        first = await get_or_create_user(db, oidc_subject_hash=subject_hash, display_name="First Name")
        await db.commit()
        first_id = first.id

    async with async_session_factory() as db:
        second = await get_or_create_user(db, oidc_subject_hash=subject_hash, display_name="Second Name")
        await db.commit()

    assert second.id == first_id
    # A returning login doesn't overwrite display_name — same
    # "idempotent, resolves to the existing row as-is" semantics as the
    # rest of this module.
    assert second.display_name == "First Name"


async def test_concurrent_first_logins_for_the_same_subject_create_exactly_one_user(
    db_available: bool,
) -> None:
    """Unlike this codebase's other TOCTOU races (e.g. two_racing_sessions
    in conftest.py), this one needs no manually forced interleaving: a
    concurrent INSERT violating a unique index blocks at the database
    engine level until the first transaction resolves, then fails — so
    asyncio.gather across two real, independent sessions reliably
    exercises the begin_nested()/IntegrityError path every time, not just
    when Python happens to schedule the awaits a particular way."""
    subject_hash = hash_oidc_subject(provider="google", subject=str(uuid.uuid4()))

    async def login() -> uuid.UUID:
        async with async_session_factory() as db, db.begin():
            user = await get_or_create_user(db, oidc_subject_hash=subject_hash, display_name="Racer")
            return user.id

    first_id, second_id = await asyncio.gather(login(), login())
    assert first_id == second_id

    async with async_session_factory() as db:
        rows = list((await db.execute(select(User).where(User.oidc_subject_hash == subject_hash))).scalars())
    assert len(rows) == 1
    assert rows[0].id == first_id
