"""Real Google OIDC login — FR-AUTH-001, replacing the session_service
dev/test seam for any caller that reaches the API through a browser.

Browser-navigation endpoints (redirects), unlike every other router in
this layer: a login necessarily starts before any session/bearer token
exists, so there's no Authorization header to check here — the whole
point of these two routes is to produce the session the rest of the API
then requires.

CSRF protection on the OAuth `state` parameter is the standard
double-submit-cookie pattern: /google/login sets a short-lived, httponly
cookie holding a random nonce and sends the same nonce as `state`;
/google/callback compares the two. No server-side state storage — not
Redis (test_side_effect_boundary.py reserves the broker for the outbox
transport only, and a signed/stored nonce would be the wrong tool for a
single-browser-redirect round trip anyway), not a new table — just the
cookie the browser already carries back on the one request that matters.

The cookie's `path` is pinned explicitly to this router's own prefix
rather than left to the browser's default (the request URL's directory)
— that default happens to work today only because /login and /callback
share the same "/v1/auth/google" directory; pinning it removes that
coincidence as a load-bearing fact, so renaming either route later can't
silently break the CSRF check.
"""

import secrets

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from doda.application.oidc_login_service import (
    GoogleLoginSettings,
    OidcNotConfiguredError,
    complete_google_login,
)
from doda.config import get_settings
from doda.db import async_session_factory
from doda.infrastructure.google_oidc_client import build_authorization_url

router = APIRouter(prefix="/v1/auth", tags=["auth"])

STATE_COOKIE_NAME = "doda_oidc_state"
STATE_COOKIE_MAX_AGE_SECONDS = 600
STATE_COOKIE_PATH = "/v1/auth/google"


def _google_login_settings() -> GoogleLoginSettings:
    settings = get_settings()
    if settings.google_oauth_client_id is None or settings.google_oauth_client_secret is None:
        raise OidcNotConfiguredError(
            "DODA_GOOGLE_OAUTH_CLIENT_ID/DODA_GOOGLE_OAUTH_CLIENT_SECRET are not set"
        )
    return GoogleLoginSettings(
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret.get_secret_value(),
        redirect_uri=settings.google_oauth_redirect_uri,
    )


@router.get("/google/login")
async def start_google_login() -> RedirectResponse:
    login_settings = _google_login_settings()
    state = secrets.token_urlsafe(32)
    redirect = RedirectResponse(
        build_authorization_url(
            client_id=login_settings.client_id,
            redirect_uri=login_settings.redirect_uri,
            state=state,
        )
    )
    redirect.set_cookie(
        STATE_COOKIE_NAME,
        state,
        max_age=STATE_COOKIE_MAX_AGE_SECONDS,
        path=STATE_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        # Google always calls back over https in any real deployment;
        # only a plain-http local-dev redirect_uri should get a non-Secure
        # cookie, or the browser would silently drop it.
        secure=login_settings.redirect_uri.startswith("https://"),
    )
    return redirect


@router.get("/google/callback")
async def google_login_callback(
    request: Request, code: str = Query(...), state: str = Query(...)
) -> RedirectResponse:
    login_settings = _google_login_settings()
    async with async_session_factory() as db, db.begin():
        session_record = await complete_google_login(
            db,
            settings=login_settings,
            code=code,
            state=state,
            cookie_state=request.cookies.get(STATE_COOKIE_NAME),
        )

    redirect = RedirectResponse(
        f"{get_settings().frontend_base_url}/auth/callback?session_id={session_record.id}"
    )
    redirect.delete_cookie(STATE_COOKIE_NAME, path=STATE_COOKIE_PATH)
    return redirect
