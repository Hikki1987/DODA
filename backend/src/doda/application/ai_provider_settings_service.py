"""Administrative provider settings — the "configured" vs "enabled" vs
"verified working" distinction the multi-provider instruction asks for.
Three separate facts, deliberately never conflated:

1. **Configured** — a server-wide `doda.config.Settings` API key exists
   (`doda.ai.factory.is_provider_configured`). This module doesn't decide
   that; it only reads it.
2. **Enabled** — a CustomerOwner has not explicitly turned this provider
   off for their customer (`CustomerAIProviderSetting`; row absence means
   enabled, same convention as `notification_service`'s preferences).
   Checked by `assert_provider_enabled` before every gateway call
   (`doda.application.conversation_service.stream_message`), so a
   disabled provider is refused with a clear reason — never silently
   routed to anyway, and never silently substituted for a different
   provider (the "risk in itself" that would be, per the explicit
   multi-provider instruction).
3. **Verified working** — whether the LAST real test call to this
   provider's API actually succeeded (`AIProviderVerification`), and
   when. Server-wide, not per customer — see that model's own docstring
   for why. A provider can be "configured" (a key exists) and "enabled"
   (no customer has disabled it) while still never having been verified,
   or having last failed — the settings UI must show all three facts
   separately, never collapse them into one status.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from doda.ai.errors import ModelGatewayError
from doda.ai.factory import get_gateway, is_provider_configured
from doda.ai.types import ChatMode, ChatRole, ChatTurn, Provider
from doda.application.ai_preference_service import default_model_for
from doda.config import Settings
from doda.domain.ai_provider_settings.models import (
    AIProviderVerification,
    CustomerAIFallbackSetting,
    CustomerAIProviderSetting,
    SettingsProvider,
)


class ProviderDisabledError(Exception):
    def __init__(self, provider: Provider) -> None:
        self.provider = provider
        super().__init__(f"{provider.value} has been disabled for this customer")


async def is_provider_enabled_for_customer(
    session: AsyncSession, *, customer_id: uuid.UUID, provider: Provider
) -> bool:
    setting = await session.get(CustomerAIProviderSetting, (customer_id, SettingsProvider(provider.value)))
    return setting is None or setting.enabled


async def assert_provider_enabled(
    session: AsyncSession, *, customer_id: uuid.UUID, provider: Provider
) -> None:
    if not await is_provider_enabled_for_customer(session, customer_id=customer_id, provider=provider):
        raise ProviderDisabledError(provider)


async def set_provider_enabled_for_customer(
    session: AsyncSession, *, customer_id: uuid.UUID, provider: Provider, enabled: bool
) -> CustomerAIProviderSetting:
    """Race-safe "set X" upsert — same shape as `ai_preference_service.
    set_user_ai_preference`/`notification_service.set_notification_
    preference`: two concurrent saves both seeing no existing row both
    try to insert; the loser's IntegrityError is caught and its own
    value applied to the row the winner just committed."""
    key = (customer_id, SettingsProvider(provider.value))
    setting = await session.get(CustomerAIProviderSetting, key)
    if setting is not None:
        setting.enabled = enabled
        await session.flush()
        return setting

    setting = CustomerAIProviderSetting(
        customer_id=customer_id, provider=SettingsProvider(provider.value), enabled=enabled
    )
    try:
        async with session.begin_nested():
            session.add(setting)
            await session.flush()
    except IntegrityError:
        setting = await session.get(CustomerAIProviderSetting, key)
        assert setting is not None
        setting.enabled = enabled
        await session.flush()
    return setting


async def is_fallback_enabled_for_customer(session: AsyncSession, *, customer_id: uuid.UUID) -> bool:
    """Row absence means DISABLED — the opposite default from
    `is_provider_enabled_for_customer` above, deliberately (see
    `CustomerAIFallbackSetting`'s own docstring: automatic substitution
    without being asked must never be the silent default)."""
    setting = await session.get(CustomerAIFallbackSetting, customer_id)
    return setting is not None and setting.enabled


async def set_fallback_enabled_for_customer(
    session: AsyncSession, *, customer_id: uuid.UUID, enabled: bool
) -> CustomerAIFallbackSetting:
    """Same race-safe upsert shape as `set_provider_enabled_for_customer`."""
    setting = await session.get(CustomerAIFallbackSetting, customer_id)
    if setting is not None:
        setting.enabled = enabled
        await session.flush()
        return setting

    setting = CustomerAIFallbackSetting(customer_id=customer_id, enabled=enabled)
    try:
        async with session.begin_nested():
            session.add(setting)
            await session.flush()
    except IntegrityError:
        setting = await session.get(CustomerAIFallbackSetting, customer_id)
        assert setting is not None
        setting.enabled = enabled
        await session.flush()
    return setting


# OPENAI first (the system-wide default, ADR-008) — deterministic and
# documented rather than "whichever happens to be configured", so a
# customer can predict which provider their chat silently continues on.
FALLBACK_ORDER: tuple[Provider, ...] = (Provider.OPENAI, Provider.CLAUDE, Provider.GEMINI)


async def pick_fallback_provider(
    session: AsyncSession, *, customer_id: uuid.UUID, excluding: Provider, settings: Settings
) -> Provider | None:
    """The first OTHER provider that is both configured (a key exists)
    and enabled for this customer — never the one that just failed, and
    never a provider this customer has explicitly turned off. Returns
    None if no eligible substitute exists, which the caller must treat
    as "no fallback possible", not as "try the failed provider again"."""
    for candidate in FALLBACK_ORDER:
        if candidate is excluding:
            continue
        if not is_provider_configured(candidate, settings):
            continue
        if await is_provider_enabled_for_customer(session, customer_id=customer_id, provider=candidate):
            return candidate
    return None


_TEST_CONNECTION_PROMPT = "Reply with the single word OK."
_TEST_CONNECTION_MAX_OUTPUT_TOKENS = 16


async def test_provider_connection(
    provider: Provider, settings: Settings
) -> tuple[bool, str | None, str | None]:
    """Makes one real, minimal call to `provider`'s own API — the only
    way to actually know "verified working" rather than merely
    "configured" (a key existing doesn't prove it's valid or that the
    account has quota). Returns (ok, error_type, error_message) — never
    the raw SDK exception or anything derived from the credential itself,
    same discipline as every adapter's own error translation.

    Deliberately does NOT call the gateway at all when unconfigured:
    `NullModelGateway` always "succeeds" with its fixed reply, which
    would misreport an absent key as a working connection."""
    if not is_provider_configured(provider, settings):
        return False, "ModelNotConfiguredError", "no API key is configured for this provider"

    gateway = get_gateway(provider, settings)
    model = default_model_for(settings, provider)
    try:
        async for _event in gateway.stream_chat(
            model=model,
            mode=ChatMode.FAST,
            instructions="",
            history=[ChatTurn(role=ChatRole.USER, content=_TEST_CONNECTION_PROMPT)],
            tools=[],
            max_output_tokens=_TEST_CONNECTION_MAX_OUTPUT_TOKENS,
        ):
            pass  # draining the stream is the call; nothing to inspect here
    except ModelGatewayError as exc:
        return False, type(exc).__name__, str(exc)
    return True, None, None


async def record_provider_verification(
    session: AsyncSession, *, provider: Provider, ok: bool, error_type: str | None, error_message: str | None
) -> AIProviderVerification:
    """Not tenant-scoped — use a plain session (not `tenant_scoped_
    session`), matching the model's own no-customer_id shape. Same
    race-safe upsert shape as `set_provider_enabled_for_customer` above:
    two admins pressing test-connection for the same provider at once
    both seeing no existing row both try to insert — the loser's
    IntegrityError is caught and its own (last-write-wins) result applied
    to the row the winner just committed, rather than a raw 500."""
    settings_provider = SettingsProvider(provider.value)
    now = datetime.now(UTC)

    record = await session.get(AIProviderVerification, settings_provider)
    if record is not None:
        record.last_verified_at = now
        record.last_verified_ok = ok
        record.last_error_type = error_type
        record.last_error = error_message
        await session.flush()
        return record

    record = AIProviderVerification(
        provider=settings_provider,
        last_verified_at=now,
        last_verified_ok=ok,
        last_error_type=error_type,
        last_error=error_message,
    )
    try:
        async with session.begin_nested():
            session.add(record)
            await session.flush()
    except IntegrityError:
        record = await session.get(AIProviderVerification, settings_provider)
        assert record is not None
        record.last_verified_at = now
        record.last_verified_ok = ok
        record.last_error_type = error_type
        record.last_error = error_message
        await session.flush()
    return record


async def get_verification_status(
    session: AsyncSession, *, provider: Provider
) -> AIProviderVerification | None:
    return await session.get(AIProviderVerification, SettingsProvider(provider.value))
