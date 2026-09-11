"""NFR-SEC-001's "configuration scan" verification, made concrete: the
comment on Settings.cors_allowed_origins has always said "never '*'", but
until now nothing enforced it — an operator could set
DODA_CORS_ALLOWED_ORIGINS=* and the app would start up fine, silently
combining with CORSMiddleware's allow_credentials=True into a
wildcard-with-credentials misconfiguration. No DB or running app needed:
this is pure Settings construction.
"""

import pytest
from pydantic import ValidationError

from doda.config import Settings


def test_wildcard_cors_origin_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must not contain"):
        Settings(cors_allowed_origins="*")


def test_wildcard_mixed_with_a_real_origin_is_still_rejected() -> None:
    with pytest.raises(ValidationError, match="must not contain"):
        Settings(cors_allowed_origins="http://localhost:3000, *")


def test_a_normal_origin_list_is_accepted() -> None:
    settings = Settings(cors_allowed_origins="http://localhost:3000,https://app.example.com")
    assert settings.cors_allowed_origins == "http://localhost:3000,https://app.example.com"


def test_telegram_bot_token_never_appears_in_the_settings_repr() -> None:
    """config.py's own docstring promises SecretStr makes "never logged"
    structural: a stray `logger.info(..., settings=settings)`, an
    unhandled-exception traceback that includes local variables, or any
    other accidental str()/repr() of the Settings object must never put
    the raw token in a log line or crash report — 12.3's "never logged"
    rule, enforced by type rather than left to every future call site to
    remember on its own.
    """
    settings = Settings(telegram_bot_token="super-secret-bot-token")  # type: ignore[call-arg]

    assert "super-secret-bot-token" not in repr(settings)
    assert "super-secret-bot-token" not in str(settings)
    assert "super-secret-bot-token" not in repr(settings.telegram_bot_token)
    # And the real value is still reachable where it's actually needed.
    assert settings.telegram_bot_token is not None
    assert settings.telegram_bot_token.get_secret_value() == "super-secret-bot-token"


def test_database_urls_never_appear_in_the_settings_repr() -> None:
    """Same guarantee as the Telegram token test above, for the two fields
    that embed a raw DB password in their URL. database_url is read by
    every running process (db.py's module-level engine); migration_database_url
    additionally carries the Postgres bootstrap superuser's credentials
    (ADR-005) — arguably the more sensitive of the two.
    """
    settings = Settings(
        database_url="postgresql+asyncpg://doda_app:super-secret-db-pw@localhost:5432/doda",  # type: ignore[call-arg]
        migration_database_url="postgresql+asyncpg://doda:super-secret-super-pw@localhost:5432/doda",  # type: ignore[call-arg]
    )

    assert "super-secret-db-pw" not in repr(settings)
    assert "super-secret-super-pw" not in repr(settings)
    assert settings.database_url.get_secret_value().endswith("super-secret-db-pw@localhost:5432/doda")
    assert settings.migration_database_url.get_secret_value().endswith(
        "super-secret-super-pw@localhost:5432/doda"
    )


def test_redis_url_never_appears_in_the_settings_repr() -> None:
    """Same guarantee, for redis_url. The default carries no password, but a
    managed/production Redis (Redis Cloud, Upstash, ElastiCache with AUTH)
    commonly embeds one in this exact URL shape, same as the database URLs
    above — nothing about a plain `str` field would have protected it."""
    settings = Settings(
        redis_url="redis://:super-secret-redis-pw@localhost:6379/0"  # type: ignore[call-arg]
    )

    assert "super-secret-redis-pw" not in repr(settings)
    assert settings.redis_url.get_secret_value() == "redis://:super-secret-redis-pw@localhost:6379/0"


def test_google_oauth_client_secret_never_appears_in_the_settings_repr() -> None:
    """Same guarantee as the Telegram/database/Redis secrets above, for
    FR-AUTH-001's OIDC client secret — the client id is deliberately a
    plain str (it is meant to appear in a browser-visible redirect URL),
    but the secret gets the same SecretStr treatment."""
    settings = Settings(
        google_oauth_client_id="not-secret-client-id",
        google_oauth_client_secret="super-secret-oauth-client-secret",  # type: ignore[call-arg]
    )

    assert "super-secret-oauth-client-secret" not in repr(settings)
    assert "not-secret-client-id" in repr(settings)
    assert settings.google_oauth_client_secret is not None
    assert settings.google_oauth_client_secret.get_secret_value() == "super-secret-oauth-client-secret"
