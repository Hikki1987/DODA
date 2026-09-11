"""Google OAuth 2.0 / OIDC client — FR-AUTH-001, the real login provider.

Infrastructure layer because it speaks to an external provider over HTTP
(6.2: the web/API layer never connects to an external provider directly,
and domain/application code doesn't either — see `oidc_login_service.py`
for why the application layer calls straight into this module instead of
going through the outbox/relay chain `test_side_effect_boundary.py`
otherwise requires: that chain exists for *actions* with an approval/audit
trail behind them, and a login redirect has no asynchronous worker on the
other end to hand off to — the browser is waiting on this HTTP response
for the next hop, same as `telegram_client.py` is infrastructure-only but
the analogy stops there).

Deliberately does not verify the `id_token` JWT locally (no JWKS fetch, no
signature check) — instead it calls Google's own `userinfo` endpoint with
the access token the code exchange returned, which Google validates
server-side before answering. This is Google's own documented alternative
to local verification and avoids adding a JWT/JWKS dependency for a single
provider. KNOWN LIMITATION: this trusts Google's TLS identity rather than
an independent cryptographic check of the token's signature — acceptable
for this stage, worth revisiting if/when a JWT library is justified
elsewhere too.

Security note, same discipline as `telegram_client.py`: the client secret
is sent only in the token-exchange POST body, never logged or included in
an error message — every error path here uses only `type(exc).__name__`,
never an httpx exception's own string form (which can echo request
details).
"""

import dataclasses
from typing import Any
from urllib.parse import urlencode

import httpx

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 — not a secret, an endpoint URL
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


class GoogleOidcError(Exception):
    """Any failure talking to Google — network error, non-2xx response, or
    a malformed/incomplete body. Safe to surface to a client 1:1 (never
    carries the client secret or an access token — see module docstring)."""


@dataclasses.dataclass(frozen=True)
class GoogleUserInfo:
    subject: str
    display_name: str


def build_authorization_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    """Pure — no I/O. The browser, not this backend, makes the actual
    request to this URL."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


async def exchange_code_for_access_token(
    http_client: httpx.AsyncClient,
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> str:
    """Authorization-code exchange. Raises GoogleOidcError on any failure;
    never includes `client_secret` or `code` in the exception message."""
    try:
        response = await http_client.post(
            TOKEN_ENDPOINT,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            timeout=10.0,
        )
        body: dict[str, Any] = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise GoogleOidcError(f"token exchange request failed: {type(exc).__name__}") from None

    if not response.is_success:
        raise GoogleOidcError(
            f"token exchange rejected: HTTP {response.status_code}, error={body.get('error', '<none>')!r}"
        )
    access_token = body.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise GoogleOidcError("token exchange response missing access_token")
    return access_token


async def login_with_google(
    *, client_id: str, client_secret: str, code: str, redirect_uri: str
) -> GoogleUserInfo:
    """Combined exchange + userinfo fetch, owning its own httpx.AsyncClient
    lifecycle. This is the one function application code should call
    (oidc_login_service.py) — it, not the caller, is responsible for the
    outbound HTTP client, same as every other infrastructure boundary in
    this codebase (e.g. telegram_relay.py owns its client, not
    action_service.py)."""
    async with httpx.AsyncClient() as http_client:
        access_token = await exchange_code_for_access_token(
            http_client,
            client_id=client_id,
            client_secret=client_secret,
            code=code,
            redirect_uri=redirect_uri,
        )
        return await fetch_userinfo(http_client, access_token=access_token)


async def fetch_userinfo(http_client: httpx.AsyncClient, *, access_token: str) -> GoogleUserInfo:
    """Doubles as the access token's validation — Google's userinfo
    endpoint rejects an invalid/expired/revoked token itself."""
    try:
        response = await http_client.get(
            USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
        body: dict[str, Any] = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise GoogleOidcError(f"userinfo request failed: {type(exc).__name__}") from None

    if not response.is_success:
        raise GoogleOidcError(f"userinfo request rejected: HTTP {response.status_code}")
    subject = body.get("sub")
    if not isinstance(subject, str) or not subject:
        raise GoogleOidcError("userinfo response missing 'sub'")
    display_name = body.get("name") or body.get("email") or "Google user"
    return GoogleUserInfo(subject=subject, display_name=display_name)
