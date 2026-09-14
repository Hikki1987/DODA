from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from doda.ai.types import Provider


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

    @field_validator("database_url", "migration_database_url", mode="before")
    @classmethod
    def _default_to_the_asyncpg_driver(cls, value: object) -> object:
        """Managed Postgres providers (Render, Railway, Supabase, Heroku-
        style hosts) hand out a plain `postgres://...`/`postgresql://...`
        connection string with no driver suffix — SQLAlchemy's async engine
        needs `+asyncpg` explicitly, or create_async_engine resolves to a
        sync driver that isn't even installed here and raises at import
        time (db.py builds the engine at module scope, so this fails before
        the app can even start, let alone answer a health check). Rewriting
        the scheme here means the exact value a provider's dashboard
        generates just works, instead of requiring every operator to
        hand-edit it in that platform's env var UI. Only a bare
        `postgres(ql)://` is rewritten — a value that already names a
        driver (`+asyncpg`, `+psycopg`, ...) is left alone."""
        if not isinstance(value, str):
            return value
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgresql://")
        return value

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

    # ADR-008/ADR-009: three real chat-AI provider adapters, each with its
    # own server-side credential — per the explicit instruction "Har bir
    # provayder uchun alohida server konfiguratsiyasi va maxfiy kalit
    # boshqaruvi" (each provider gets its own server config and secret
    # management), never one shared key and never a key typed into the
    # frontend. SecretStr for the same "never logged" reason as every
    # other credential field above. None means "this provider has no
    # credential configured": doda.ai.factory wires
    # doda.ai.port.NullModelGateway for it in that case, never a crash
    # and never a silent substitution of a different provider.
    openai_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    claude_api_key: SecretStr | None = None
    # System-wide fallback when no conversation/user/workspace override
    # exists (doda.application.ai_preference_service) — explicit Product
    # Owner decision: OpenAI. Stored as a plain string (not the Provider
    # enum) so an invalid value fails loudly at Settings construction via
    # the validator below, rather than deep inside a request.
    ai_default_provider: str = "OPENAI"

    @field_validator("ai_default_provider")
    @classmethod
    def _validate_default_provider(cls, value: str) -> str:
        if value not in Provider.__members__:
            raise ValueError(
                f"ai_default_provider must be one of {list(Provider.__members__)}, got {value!r}"
            )
        return value

    # One default model per provider — "eng sodda, asoslangan
    # konfiguratsiyadan boshla" (start from the simplest, justified
    # configuration) applied per-provider rather than across three
    # FAST/STANDARD/DEEP tiers of the SAME provider, now that provider
    # itself is the primary axis a user picks. Sourcing (2026-09-12, see
    # ADR-008/ADR-009 for the full note):
    #   - gpt-5-mini: `openai` SDK 3.13.0's own ChatModel literal.
    #   - claude-sonnet-5: `anthropic` SDK 1.5.0's own ModelParam literal;
    #     this is the model actively serving this very session.
    #   - gemini-3.1-flash-lite: `google-genai` SDK 2.23.0's own model-id
    #     strings; gemini-2.5-flash (an earlier candidate) was rejected
    #     because independent pricing sources flag it as scheduled for
    #     deprecation 2026-10-16, about a month from this decision date.
    # Pricing for all three is a multi-source web consensus, NOT a
    # primary-source confirmation — every provider's own pricing page is
    # blocked by this environment's network policy (verified with curl:
    # platform.openai.com, docs.anthropic.com, ai.google.dev all return
    # a proxy-level connect rejection). Re-verify before relying on this
    # for real billing reconciliation.
    ai_model_openai: str = "gpt-5-mini"
    ai_model_claude: str = "claude-sonnet-5"
    ai_model_gemini: str = "gemini-3.1-flash-lite"
    # TRD 7.2's FAST/STANDARD/DEEP tiers — now purely an output-length/
    # cost-ceiling selector, orthogonal to provider/model choice (see
    # doda.ai.types.ChatMode).
    ai_max_output_tokens_fast: int = 512
    ai_max_output_tokens_standard: int = 1024
    ai_max_output_tokens_deep: int = 4096
    # FR-CONV-002: a request that hangs must not hang the HTTP response
    # forever. Applies to the whole gateway call, not just connect time.
    ai_request_timeout_seconds: float = 30.0
    # "agent qadamlariga limit" — the max number of tool-call round trips
    # the gateway will make within one user turn before it must produce a
    # final answer instead. Bounds both cost and the chance of a runaway
    # tool-call loop.
    ai_max_tool_rounds: int = 4
    # How much conversation history (by character count, not tokens — no
    # tokenizer dependency needed for a first-pass budget) is sent as
    # context per request. "tegishli va hajmi cheklangan kontekstni tanla"
    # — the simplest defensible choice: most-recent messages first, up to
    # this budget, no retrieval/summarization (Knowledge/RAG doesn't
    # exist yet to do either).
    ai_max_context_chars: int = 8000
    # OD-008: Product Owner gave $20-$100/month as a starting working
    # range, not a final figure. soft = a warning threshold surfaced to
    # the caller but the request still proceeds; hard = the request is
    # refused before any provider call is made. Per customer, per
    # calendar month (doda.application.ai_budget_service).
    ai_budget_soft_usd_per_customer_month: float = 20.0
    ai_budget_hard_usd_per_customer_month: float = 80.0
    # DEEP mode's own, separate per-request ceiling (TRD instruction:
    # "DEEP — ... alohida xarajat cheklovi bilan") — independent of the
    # shared monthly budget above, so one unusually large DEEP request
    # can't alone consume a big share of the whole month's budget.
    ai_deep_request_cost_ceiling_usd: float = 2.0

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
