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
    # how the unprivileged `doda_app` role is provisioned.
    database_url: str = "postgresql+asyncpg://doda_app:doda_app@localhost:5432/doda"
    # Alembic only: needs superuser to CREATE EXTENSION vector/pgcrypto and
    # run arbitrary DDL. Never used for application runtime queries.
    migration_database_url: str = "postgresql+asyncpg://doda:doda@localhost:5432/doda"
    redis_url: str = "redis://localhost:6379/0"
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
