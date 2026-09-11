from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration. See docs/DODA-TRD-v2.0.docx section 6.3 for stack rationale."""

    model_config = SettingsConfigDict(env_prefix="DODA_", env_file=".env", extra="ignore")

    env: str = "local"
    # ADR-005: the app must never run as the Postgres bootstrap superuser —
    # superusers always bypass row security, FORCE ROW LEVEL SECURITY or
    # not, so RLS would silently do nothing. See infra/postgres-init for
    # how the unprivileged `doda_app` role is provisioned. SecretStr (not
    # str) for the same reason as telegram_bot_token below: the password is
    # embedded in this URL, and a stray `logger.info(..., settings=...)` or
    # an exception traceback showing local variables must not put it in a
    # log line or crash report.
    database_url: SecretStr = SecretStr("postgresql+asyncpg://doda_app:doda_app@localhost:5432/doda")
    # Alembic only: needs superuser to CREATE EXTENSION vector/pgcrypto and
    # run arbitrary DDL. Never used for application runtime queries.
    migration_database_url: SecretStr = SecretStr("postgresql+asyncpg://doda:doda@localhost:5432/doda")
    # SecretStr for the same reason as the two database URLs above: the
    # default here carries no password, but a managed/production Redis
    # (Redis Cloud, Upstash, ElastiCache with AUTH) commonly embeds one in
    # this exact URL, and nothing about this field's shape would tell a
    # future reader that. Same structural protection, not a speculative one.
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_bucket: str = "doda-files"
    otel_service_name: str = "doda-backend"
    # OD-002: first real connector. Read only by infrastructure/telegram_*
    # (the connector itself) -- never by domain/application code, never
    # logged, never put in an audit safe_metadata dict. SecretStr rather
    # than str makes "never logged" structural instead of a comment someone
    # has to remember: repr()/str() of a SecretStr (and so a stray
    # `logger.info(..., settings=settings)` or FastAPI's own startup repr)
    # render "**********", not the raw token. Optional (None) so every
    # environment that doesn't run the Telegram connector (tests, CI, local
    # dev without it configured) is unaffected.
    telegram_bot_token: SecretStr | None = None
    # FR-AUTH-001: real Google OIDC login. Optional (None) so every
    # environment that doesn't run real login (tests, CI, local dev still
    # using the session_service dev/test seam) is unaffected — api/auth.py
    # raises a clear OidcNotConfiguredError rather than a confusing
    # provider error when these are unset. Client ID is not sensitive (it
    # is meant to appear in a browser-visible redirect URL); the secret is,
    # for the same "never logged" reason as telegram_bot_token above.
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None
    # Must exactly match an "Authorized redirect URI" registered on the
    # Google Cloud OAuth client, or Google rejects the exchange outright.
    # Defaults to a local dev value; a real deployment overrides this via
    # env, not by editing code.
    google_oauth_redirect_uri: str = "http://localhost:8000/v1/auth/google/callback"
    # Where the callback hands the browser off to after minting a session
    # (?session_id=... appended) — the frontend's own /auth/callback route
    # reads it into localStorage. Separate from cors_allowed_origins, which
    # may legitimately list more than one origin; this is exactly one.
    frontend_base_url: str = "http://localhost:3000"
    # Comma-separated origins the Experience layer (web frontend) is served
    # from. Never "*" — every request here already carries a bearer session
    # token, and a wildcard would let any origin's script read the response.
    cors_allowed_origins: str = "http://localhost:3000"

    @field_validator("cors_allowed_origins")
    @classmethod
    def _reject_wildcard_origin(cls, value: str) -> str:
        # NFR-SEC-001's "configuration scan" verification, made real: the
        # comment above has said "never *" since CORS was first wired up
        # (main.py passes this straight to CORSMiddleware's allow_origins),
        # but nothing actually stopped an operator from setting
        # DODA_CORS_ALLOWED_ORIGINS=* — combined with allow_credentials=True
        # that's a wildcard-with-credentials misconfiguration, a well-known
        # CORS anti-pattern. Fail fast at startup instead of accepting it.
        if any(origin.strip() == "*" for origin in value.split(",")):
            raise ValueError(
                "DODA_CORS_ALLOWED_ORIGINS must not contain '*' — every "
                "response here carries a bearer session token; list the "
                "exact origin(s) allowed to read it instead"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
