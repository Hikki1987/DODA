"""Google OIDC login orchestration — FR-AUTH-001.

This is the first application-layer module that calls straight into
`infrastructure/` (checked: no other `application/*.py` did, before this).
That is deliberate, not an accidental shortcut around the outbox/relay
chain `test_side_effect_boundary.py` enforces for external side effects:
that chain exists for *actions* with an approval/idempotency/audit trail
behind them and an asynchronous worker on the other end. A login redirect
has neither — the browser is blocked on this exact HTTP response for the
next hop, so there is nothing to hand off to a worker. Authentication
bootstrapping and action execution are different categories; this module
is the first concrete case of the first one.

`api/auth.py` stays a thin HTTP shell around this: it owns only the two
things a service function shouldn't — the state cookie and the redirect
response — everything else (state comparison, the provider exchange,
minting the User/Session) lives here so it's testable without a running
ASGI app.
"""

import dataclasses
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from doda.application.identity_service import get_or_create_user, hash_oidc_subject
from doda.application.session_service import create_session, is_new_device_login
from doda.domain.identity.models import AuthStrength, Session
from doda.infrastructure.google_oidc_client import login_with_google

OIDC_PROVIDER = "google"


class OidcNotConfiguredError(Exception):
    """DODA_GOOGLE_OAUTH_CLIENT_ID/SECRET are unset — this environment
    cannot run real login yet (see config.py)."""


class OidcStateMismatchError(Exception):
    """The callback's `state` query param didn't match the cookie set by
    /login — either the login flow expired (cookie gone after
    STATE_COOKIE_MAX_AGE_SECONDS) or this is a forged callback (CSRF).
    Deliberately one exception/one message for both, same reasoning as
    SessionInvalidError: not helping an attacker distinguish the two."""


@dataclasses.dataclass(frozen=True)
class GoogleLoginSettings:
    client_id: str
    client_secret: str
    redirect_uri: str


@dataclasses.dataclass(frozen=True)
class GoogleLoginResult:
    session: Session
    is_new_device: bool
    """FR-AUTH-007: true iff this login's user_agent has never been seen
    on any of this user's prior sessions. api/auth.py is responsible for
    turning this into a security notification — that write is
    customer-scoped (Notification is a tenant-scoped table) while this
    whole login flow is not, so it can't happen inside this function."""


async def complete_google_login(
    db: AsyncSession,
    *,
    settings: GoogleLoginSettings,
    code: str,
    state: str,
    cookie_state: str | None,
    user_agent: str | None = None,
) -> GoogleLoginResult:
    """Validate CSRF state, exchange the code, and mint/resolve the User +
    Session. Raises OidcStateMismatchError or GoogleOidcError (see
    infrastructure/google_oidc_client.py) on failure — neither is caught
    here, both are mapped to an HTTP response by api/errors.py."""
    if not cookie_state or not secrets.compare_digest(cookie_state, state):
        raise OidcStateMismatchError("oidc state mismatch")

    userinfo = await login_with_google(
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        code=code,
        redirect_uri=settings.redirect_uri,
    )

    user = await get_or_create_user(
        db,
        oidc_subject_hash=hash_oidc_subject(provider=OIDC_PROVIDER, subject=userinfo.subject),
        display_name=userinfo.display_name,
    )
    # Checked BEFORE create_session, which would otherwise count its own
    # new row as evidence of this exact device already being known.
    is_new_device = (
        await is_new_device_login(db, user_id=user.id, user_agent=user_agent) if user_agent else False
    )
    # AAL1, not AAL2: a Google login alone is not this app's own "fresh
    # MFA" proof (FR-AUTH-004/9.1) — AAL2 is established at approval time
    # for R3+ actions, a separate, narrower step-up this flow doesn't
    # attempt to satisfy just because Google itself may have required MFA.
    session_record = await create_session(
        db, user_id=user.id, auth_strength=AuthStrength.AAL1, user_agent=user_agent
    )
    return GoogleLoginResult(session=session_record, is_new_device=is_new_device)
