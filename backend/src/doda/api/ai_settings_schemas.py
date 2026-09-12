from datetime import datetime

from pydantic import BaseModel

from doda.ai.types import Provider


class ProviderStatusOut(BaseModel):
    provider: Provider
    configured: bool
    """A server-wide API key exists (doda.config.Settings) — not a claim
    that it actually works, see `verified_ok`."""
    enabled: bool
    """Whether this customer's CustomerOwner has left this provider on."""
    verified_at: datetime | None
    verified_ok: bool | None
    """None means never tested since this server started tracking it."""
    verified_error: str | None


class SetProviderEnabledRequest(BaseModel):
    enabled: bool


class TestProviderConnectionOut(BaseModel):
    provider: Provider
    ok: bool
    error: str | None


class AIPreferenceOut(BaseModel):
    provider: Provider | None
    """None means no override is set at this tier — the next tier down
    (or the system default) decides."""
    model: str | None


class SetAIPreferenceRequest(BaseModel):
    provider: Provider
    model: str | None = None


class AIFallbackSettingOut(BaseModel):
    enabled: bool


class SetAIFallbackSettingRequest(BaseModel):
    enabled: bool


class AIBudgetStatusOut(BaseModel):
    year_month: str
    soft_cap_usd: float
    hard_cap_usd: float
    spent_usd: float
    over_soft_budget: bool
