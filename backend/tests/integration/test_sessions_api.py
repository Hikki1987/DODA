"""FR-CTL-001/002 — session self-service, plus the regression test for a
real bug found while building this: the auth-resolution step's
last_seen_at touch (FR-AUTH-006 idle timeout reset) was silently never
persisting.
"""

import uuid
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from doda.db import async_session_factory
from doda.domain.base import utcnow
from doda.domain.identity.models import Session
from doda.main import app
from tests.integration.conftest import seed_workspace_member


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_headers(session_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


async def test_authenticated_request_persists_the_session_activity_touch(
    client: AsyncClient, db_available: bool
) -> None:
    """Regression test: get_request_context/get_current_identity used to
    call resolve_session (which updates last_seen_at) inside a bare
    `async with async_session_factory()` block with no explicit commit —
    verified experimentally that SQLAlchemy rolls back an uncommitted
    transaction on close, so the touch silently never reached the DB.
    FR-AUTH-006's idle timeout would then only ever have reset at session
    creation, never on real activity.
    """
    member = await seed_workspace_member()
    stale_time = utcnow() - timedelta(minutes=20)

    async with async_session_factory() as db:
        record = await db.get(Session, member.session_id)
        record.last_seen_at = stale_time
        await db.commit()

    response = await client.get("/v1/sessions", headers=_auth_headers(member.session_id))
    assert response.status_code == 200

    async with async_session_factory() as verify_db:
        refreshed = await verify_db.get(Session, member.session_id)
        assert refreshed.last_seen_at > stale_time + timedelta(minutes=1)


async def test_list_sessions_marks_the_current_one(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()

    response = await client.get("/v1/sessions", headers=_auth_headers(member.session_id))
    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 1
    assert sessions[0]["id"] == str(member.session_id)
    assert sessions[0]["is_current"] is True


async def test_revoking_a_session_makes_it_unusable(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()

    revoke = await client.delete(f"/v1/sessions/{member.session_id}", headers=_auth_headers(member.session_id))
    assert revoke.status_code == 204

    response = await client.get("/v1/sessions", headers=_auth_headers(member.session_id))
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_cannot_revoke_someone_elses_session(client: AsyncClient, db_available: bool) -> None:
    member = await seed_workspace_member()
    other = await seed_workspace_member()

    response = await client.delete(
        f"/v1/sessions/{other.session_id}", headers=_auth_headers(member.session_id)
    )
    assert response.status_code == 404

    # other's session must still be perfectly usable — the attempt was a no-op.
    still_works = await client.get("/v1/sessions", headers=_auth_headers(other.session_id))
    assert still_works.status_code == 200


async def test_revoked_session_disappears_from_the_active_list(
    client: AsyncClient, db_available: bool
) -> None:
    """A revoked OTHER session of the same user shouldn't clutter the
    active list — set up a second session for the same identity by hand
    (no real login flow exists yet) and revoke it via the DB directly,
    then confirm the listing endpoint only shows the live one."""
    member = await seed_workspace_member()

    from doda.application.session_service import create_session
    from doda.domain.identity.models import AuthStrength

    async with async_session_factory() as db:
        second = await create_session(db, user_id=member.user_id, auth_strength=AuthStrength.AAL1)
        await db.commit()
        second_id = second.id

    listing_before = await client.get("/v1/sessions", headers=_auth_headers(member.session_id))
    assert len(listing_before.json()) == 2

    revoke = await client.delete(f"/v1/sessions/{second_id}", headers=_auth_headers(member.session_id))
    assert revoke.status_code == 204

    listing_after = await client.get("/v1/sessions", headers=_auth_headers(member.session_id))
    ids = {s["id"] for s in listing_after.json()}
    assert ids == {str(member.session_id)}
