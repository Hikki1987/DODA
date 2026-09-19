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
import uuid

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from doda.application.customer_service import customer_ids_for_user
from doda.application.notification_service import create_notification
from doda.application.oidc_login_service import (
    GoogleLoginSettings,
    OidcNotConfiguredError,
    complete_google_login,
)
from doda.config import get_settings
from doda.db import async_session_factory, tenant_scoped_session
from doda.domain.notification.models import NotificationType
from doda.infrastructure.google_oidc_client import build_authorization_url

router = APIRouter(prefix="/v1/auth", tags=["auth"])
logger = structlog.get_logger()

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
        result = await complete_google_login(
            db,
            settings=login_settings,
            code=code,
            state=state,
            cookie_state=request.cookies.get(STATE_COOKIE_NAME),
            user_agent=request.headers.get("user-agent"),
        )

    if result.is_new_device:
        await _notify_new_device_login(user_id=result.session.user_id, session_id=result.session.id)

    redirect = RedirectResponse(
        f"{get_settings().frontend_base_url}/auth/callback?session_id={result.session.id}"
    )
    redirect.delete_cookie(STATE_COOKIE_NAME, path=STATE_COOKIE_PATH)
    return redirect


async def _notify_new_device_login(*, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
    """FR-AUTH-007: one SECURITY_ALERT notification per customer the user
    belongs to — Notification is a tenant-scoped table (no user-level
    inbox exists, same reason FR-CTL-002's export iterates customers
    rather than reading one global row), so a user-level event fans out
    to every customer context it could be relevant in. A user with no
    customer membership yet (rare once a prior session exists at all, but
    possible) simply gets no notification — there is no tenant to attach
    one to, not a bug. The login itself already committed by the time
    this runs, so any failure here is caught and logged rather than
    turning an already-successful login into a 500 for the user — same
    "best-effort side action" posture as the frontend's logOut()
    swallowing a failed revoke-session call."""
    try:
        for customer_id in await customer_ids_for_user(user_id):
            async with tenant_scoped_session(customer_id) as db:
                await create_notification(
                    db,
                    customer_id=customer_id,
                    recipient_id=f"user:{user_id}",
                    notification_type=NotificationType.SECURITY_ALERT,
                    reference_type="session",
                    reference_id=session_id,
                    safe_metadata={"reason": "new_device_login"},
                )
    except Exception:
        logger.exception("auth.new_device_notification_failed", user_id=str(user_id))
