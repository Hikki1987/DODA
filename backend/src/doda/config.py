from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
