"""Unit tests for the Google OIDC client's request/response handling.

Same technique and same honest limitation as test_telegram_client.py:
httpx.MockTransport stands in for the network, never a real call to
Google. Whether this client actually works against the real Google OAuth
service has not been verified anywhere in this codebase.
"""

import httpx
import pytest

from doda.infrastructure.google_oidc_client import (
    GoogleOidcError,
    build_authorization_url,
    exchange_code_for_access_token,
    fetch_userinfo,
    login_with_google,
)


def test_authorization_url_carries_client_id_redirect_uri_and_state() -> None:
    url = build_authorization_url(
        client_id="client-123", redirect_uri="https://example.com/callback", state="nonce-abc"
    )
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=client-123" in url
    assert "redirect_uri=https%3A%2F%2Fexample.com%2Fcallback" in url
    assert "state=nonce-abc" in url
    assert "scope=openid+email+profile" in url


async def test_successful_exchange_returns_the_access_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://oauth2.googleapis.com/token"
        return httpx.Response(200, json={"access_token": "tok-xyz", "token_type": "Bearer"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    token = await exchange_code_for_access_token(
        client, client_id="cid", client_secret="super-secret", code="code-1", redirect_uri="https://x/cb"
    )
    assert token == "tok-xyz"


async def test_exchange_request_carries_the_expected_form_fields() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        from urllib.parse import parse_qsl

        captured.update(dict(parse_qsl(request.content.decode())))
        return httpx.Response(200, json={"access_token": "tok"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await exchange_code_for_access_token(
        client, client_id="cid", client_secret="csecret", code="the-code", redirect_uri="https://x/cb"
    )
    assert captured == {
        "client_id": "cid",
        "client_secret": "csecret",
        "code": "the-code",
        "grant_type": "authorization_code",
        "redirect_uri": "https://x/cb",
    }


async def test_rejected_exchange_raises_google_oidc_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(GoogleOidcError, match="invalid_grant"):
        await exchange_code_for_access_token(
            client, client_id="cid", client_secret="csecret", code="stale-code", redirect_uri="https://x/cb"
        )


async def test_exchange_response_missing_access_token_raises_google_oidc_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token_type": "Bearer"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(GoogleOidcError, match="missing access_token"):
        await exchange_code_for_access_token(
            client, client_id="cid", client_secret="csecret", code="code", redirect_uri="https://x/cb"
        )


async def test_network_error_raises_google_oidc_error_without_leaking_the_secret() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connection refused to {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(GoogleOidcError) as exc_info:
        await exchange_code_for_access_token(
            client,
            client_id="cid",
            client_secret="super-secret-client-secret",
            code="code",
            redirect_uri="https://x/cb",
        )
    assert "super-secret-client-secret" not in str(exc_info.value)


async def test_successful_userinfo_returns_subject_and_display_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer tok-xyz"
        return httpx.Response(200, json={"sub": "1234567890", "name": "Hikmatullo", "email": "h@example.com"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    info = await fetch_userinfo(client, access_token="tok-xyz")
    assert info.subject == "1234567890"
    assert info.display_name == "Hikmatullo"


async def test_userinfo_falls_back_to_email_when_name_is_absent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sub": "1234567890", "email": "h@example.com"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    info = await fetch_userinfo(client, access_token="tok")
    assert info.display_name == "h@example.com"


async def test_userinfo_missing_subject_raises_google_oidc_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"email": "h@example.com"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(GoogleOidcError, match="sub"):
        await fetch_userinfo(client, access_token="tok")


async def test_userinfo_network_error_raises_google_oidc_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(GoogleOidcError, match="ConnectError"):
        await fetch_userinfo(client, access_token="tok")


async def test_rejected_userinfo_request_raises_google_oidc_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_token"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(GoogleOidcError, match="401"):
        await fetch_userinfo(client, access_token="expired")


async def test_login_with_google_composes_exchange_and_userinfo(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "composed-token"})
        assert request.headers["authorization"] == "Bearer composed-token"
        return httpx.Response(200, json={"sub": "42", "name": "Composed User"})

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "doda.infrastructure.google_oidc_client.httpx.AsyncClient",
        lambda *a, **k: real_async_client(transport=httpx.MockTransport(handler)),
    )

    info = await login_with_google(
        client_id="cid", client_secret="csecret", code="code", redirect_uri="https://x/cb"
    )

    assert info.subject == "42"
    assert info.display_name == "Composed User"
