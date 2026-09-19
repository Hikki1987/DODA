"""FR-AUTH-001 — real Google OIDC login, end to end over HTTP. Only the
one true external dependency (the network call to Google) is stubbed —
`doda.application.oidc_login_service.login_with_google` — everything else
(state-cookie handling, get_or_create_user, create_session, the redirect
back to the frontend) runs for real against real Postgres, same
discipline as test_telegram_relay.py stubbing only the Telegram HTTP leg.
"""

import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from doda.application.customer_service import create_customer_with_owner, invite_customer_member
from doda.config import Settings
from doda.db import async_session_factory, tenant_scoped_session
from doda.domain.identity.models import Session, User
from doda.domain.security.roles import CustomerRole
from doda.infrastructure.google_oidc_client import GoogleOidcError, GoogleUserInfo
from doda.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _configured_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "google_oauth_client_id": "test-client-id",
        "google_oauth_client_secret": "test-client-secret",
        "google_oauth_redirect_uri": "http://localhost:8000/v1/auth/google/callback",
        "frontend_base_url": "https://frontend.example.com",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


async def test_google_login_when_not_configured_returns_503(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Explicit unconfigured Settings rather than relying on the ambient
    # .env having no Google OAuth values set — this test used to depend
    # on that (a real gap: a developer's own backend/.env, once it
    # carries real deployment credentials, would make this test fail for
    # a reason that has nothing to do with a regression).
    monkeypatch.setattr(
        "doda.api.auth.get_settings",
        lambda: Settings(google_oauth_client_id=None, google_oauth_client_secret=None),  # type: ignore[call-arg]
    )
    response = await client.get("/v1/auth/google/login")
    assert response.status_code == 503
    assert response.json()["code"] == "OIDC_NOT_CONFIGURED"


async def test_login_redirects_to_google_with_state_and_sets_cookie(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("doda.api.auth.get_settings", lambda: _configured_settings())

    response = await client.get("/v1/auth/google/login")

    assert response.status_code == 307
    location = urlparse(response.headers["location"])
    assert location.netloc == "accounts.google.com"
    query = parse_qs(location.query)
    assert query["client_id"] == ["test-client-id"]
    assert query["redirect_uri"] == ["http://localhost:8000/v1/auth/google/callback"]
    assert "state" in query and len(query["state"][0]) > 16
    assert "doda_oidc_state" in response.cookies
    assert response.cookies["doda_oidc_state"] == query["state"][0]
    # Pinned explicitly (api/auth.py's own docstring explains why) rather
    # than left to the browser's default path — assert it's really there,
    # not just that the round trip happens to work today.
    assert "Path=/v1/auth/google" in response.headers["set-cookie"]


async def test_login_cookie_is_marked_secure_when_redirect_uri_is_https(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "doda.api.auth.get_settings",
        lambda: _configured_settings(google_oauth_redirect_uri="https://natsecurity.uz/auth/google/callback"),
    )

    response = await client.get("/v1/auth/google/login")

    set_cookie = response.headers["set-cookie"]
    assert "Secure" in set_cookie


async def test_callback_without_matching_state_cookie_is_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("doda.api.auth.get_settings", lambda: _configured_settings())

    response = await client.get(
        "/v1/auth/google/callback", params={"code": "irrelevant", "state": "forged-state"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "OIDC_STATE_MISMATCH"


async def test_successful_callback_creates_a_session_and_redirects_to_frontend(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, db_available: bool
) -> None:
    monkeypatch.setattr("doda.api.auth.get_settings", lambda: _configured_settings())
    subject = str(uuid.uuid4())

    async def fake_login_with_google(**kwargs: object) -> GoogleUserInfo:
        assert kwargs["client_id"] == "test-client-id"
        assert kwargs["client_secret"] == "test-client-secret"
        return GoogleUserInfo(subject=subject, display_name="Real Flow User")

    monkeypatch.setattr("doda.application.oidc_login_service.login_with_google", fake_login_with_google)

    login_response = await client.get("/v1/auth/google/login")
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]

    callback_response = await client.get(
        "/v1/auth/google/callback", params={"code": "google-code-xyz", "state": state}
    )

    assert callback_response.status_code == 307
    redirect = urlparse(callback_response.headers["location"])
    assert redirect.scheme == "https"
    assert redirect.netloc == "frontend.example.com"
    assert redirect.path == "/auth/callback"
    session_id = uuid.UUID(parse_qs(redirect.query)["session_id"][0])
    # The state cookie must not survive past a successful login.
    assert callback_response.cookies.get("doda_oidc_state") in (None, "")

    async with async_session_factory() as db:
        session_record = await db.get(Session, session_id)
        assert session_record is not None
        user = await db.scalar(select(User).where(User.id == session_record.user_id))
        assert user is not None
        assert user.display_name == "Real Flow User"


async def test_callback_provider_error_returns_502(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, db_available: bool
) -> None:
    monkeypatch.setattr("doda.api.auth.get_settings", lambda: _configured_settings())

    async def failing_login_with_google(**kwargs: object) -> GoogleUserInfo:
        raise GoogleOidcError("token exchange rejected: HTTP 400, error='invalid_grant'")

    monkeypatch.setattr("doda.application.oidc_login_service.login_with_google", failing_login_with_google)

    login_response = await client.get("/v1/auth/google/login")
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]

    response = await client.get("/v1/auth/google/callback", params={"code": "stale-code", "state": state})

    assert response.status_code == 502
    assert response.json()["code"] == "OIDC_PROVIDER_ERROR"


async def test_a_new_device_login_creates_exactly_one_security_alert_per_customer(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, db_available: bool
) -> None:
    """FR-AUTH-007 end to end: first-ever login (no baseline) is quiet, a
    genuinely new device fires a SECURITY_ALERT in every customer the user
    belongs to, and a repeat of that same device never fires a second one.
    """
    monkeypatch.setattr("doda.api.auth.get_settings", lambda: _configured_settings())
    subject = str(uuid.uuid4())

    async def fake_login_with_google(**kwargs: object) -> GoogleUserInfo:
        return GoogleUserInfo(subject=subject, display_name="Device Test User")

    monkeypatch.setattr("doda.application.oidc_login_service.login_with_google", fake_login_with_google)

    async def _google_login(*, code: str, user_agent: str) -> uuid.UUID:
        login_response = await client.get("/v1/auth/google/login")
        state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]
        callback_response = await client.get(
            "/v1/auth/google/callback",
            params={"code": code, "state": state},
            headers={"User-Agent": user_agent},
        )
        assert callback_response.status_code == 307
        query = parse_qs(urlparse(callback_response.headers["location"]).query)
        return uuid.UUID(query["session_id"][0])

    # First-ever login: no prior session to compare against, so this must
    # not be flagged even though there's no customer to notify yet either.
    session1_id = await _google_login(code="code-1", user_agent="Mozilla/BrowserA")

    async with async_session_factory() as db:
        session1 = await db.get(Session, session1_id)
        assert session1 is not None
        user_id = session1.user_id

    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as tdb:
        await create_customer_with_owner(
            tdb,
            customer_id=customer_id,
            name="Device Test Customer",
            owner_user_id=uuid.uuid4(),
            actor_id="user:bootstrap",
        )
        await invite_customer_member(
            tdb,
            customer_id=customer_id,
            user_id=user_id,
            role=CustomerRole.MEMBER,
            actor_id="user:bootstrap",
        )

    # Second login, a genuinely different device — now there's a baseline.
    session2_id = await _google_login(code="code-2", user_agent="Mozilla/BrowserB")

    notifications = (
        await client.get(
            f"/v1/customers/{customer_id}/notifications",
            headers={"Authorization": f"Bearer {session2_id}"},
        )
    ).json()
    alerts = [n for n in notifications if n["notification_type"] == "SECURITY_ALERT"]
    assert len(alerts) == 1
    assert alerts[0]["reference_type"] == "session"
    assert alerts[0]["reference_id"] == str(session2_id)

    # Third login, SAME device as session2 — already-known, no new alert.
    session3_id = await _google_login(code="code-3", user_agent="Mozilla/BrowserB")

    notifications_after_third = (
        await client.get(
            f"/v1/customers/{customer_id}/notifications",
            headers={"Authorization": f"Bearer {session3_id}"},
        )
    ).json()
    alerts_after_third = [n for n in notifications_after_third if n["notification_type"] == "SECURITY_ALERT"]
    assert len(alerts_after_third) == 1
    assert alerts_after_third[0]["reference_id"] == str(session2_id)
