"""Per-provider administrative settings — the "configured" vs "enabled"
vs "verified working" distinction the multi-provider instruction asks
for (`doda.ai.factory.is_provider_configured`'s own docstring names this
module as "one layer up").

`SettingsProvider` duplicates `doda.ai.types.Provider`'s three values for
the same layering reason `UsageProvider`/`PreferenceProvider` duplicate it
elsewhere in this codebase (6.2: a Domain module never reaches up into
the AI layer) — the application layer converts between the two at the
boundary (`doda.application.ai_provider_settings_service`).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from doda.domain.base import Base


class SettingsProvider(enum.StrEnum):
    OPENAI = "OPENAI"
    GEMINI = "GEMINI"
    CLAUDE = "CLAUDE"


class CustomerAIProviderSetting(Base):
    """One row per (customer, provider) a CustomerOwner has explicitly
    disabled — same "row absence means the default (enabled)" convention
    `NotificationPreference` already uses (FR-NTF-004), not a row per
    provider per customer unconditionally."""

    __tablename__ = "ai_customer_provider_settings"

    customer_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    provider: Mapped[SettingsProvider] = mapped_column(
        SAEnum(SettingsProvider, name="ai_settings_provider", native_enum=False, length=16),
        primary_key=True,
    )
    enabled: Mapped[bool] = mapped_column(default=True)


class CustomerAIFallbackSetting(Base):
    """Opt-in, default-OFF automatic fallback — the explicit instruction:
    manual provider switching (Conversation.pinned_provider) and
    automatic fallback on a transient error are two separate mechanisms,
    never conflated; this table is ONLY the latter's on/off switch. Row
    absence means DISABLED (the opposite default convention from
    `CustomerAIProviderSetting` above, because "automatic substitution
    without being asked" is the one behavior here that must never be the
    silent default)."""

    __tablename__ = "ai_customer_fallback_settings"

    customer_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=False)


class AIProviderVerification(Base):
    """The "last time an admin pressed test-connection, and what
    happened" record — deliberately NOT customer-scoped (no customer_id
    column, same class as `identity_users`/`identity_sessions`): the API
    credential itself is a server-wide `doda.config.Settings` value, not
    a per-customer one (no BYOK model exists), so whether it actually
    works is a server-wide fact, tested once and read by every customer.
    `last_error` never carries a raw SDK exception string or any part of
    the credential — the same structured-fields-only discipline as every
    adapter's own error translation (`doda.ai.errors`)."""

    __tablename__ = "ai_provider_verifications"

    provider: Mapped[SettingsProvider] = mapped_column(
        SAEnum(SettingsProvider, name="ai_settings_provider", native_enum=False, length=16),
        primary_key=True,
    )
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_verified_ok: Mapped[bool] = mapped_column()
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    last_error_type: Mapped[str | None] = mapped_column(String(64), default=None)
