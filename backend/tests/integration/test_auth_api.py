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

from doda.config import Settings
from doda.db import async_session_factory
from doda.domain.identity.models import Session, User
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


async def test_google_login_when_not_configured_returns_503(client: AsyncClient) -> None:
    # Default Settings() has no client id/secret configured.
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
