"""Closes coverage gaps in `doda.application.ai_provider_settings_service`
that were never exercised: the race-safe upsert paths (concurrent
set/set and concurrent record/record), the "row already exists" update
branches, `pick_fallback_provider`'s skip/exhaustion logic in isolation,
and `test_provider_connection`'s real (mocked-gateway) success/failure
paths — as opposed to `test_ai_settings_api.py`'s HTTP tests, which only
ever exercise the "no provider configured at all" shortcut.
"""

import asyncio
import typing
import uuid

import pytest
from sqlalchemy import delete

from doda.ai.errors import ModelProviderError
from doda.ai.types import GatewayEvent, Provider, TextDelta
from doda.application import ai_provider_settings_service
from doda.application.ai_provider_settings_service import (
    get_verification_status,
    is_fallback_enabled_for_customer,
    is_provider_enabled_for_customer,
    pick_fallback_provider,
    record_provider_verification,
    set_fallback_enabled_for_customer,
    set_provider_enabled_for_customer,
)
from doda.config import Settings, get_settings
from doda.db import async_session_factory, tenant_scoped_session
from doda.domain.ai_provider_settings.models import AIProviderVerification


@pytest.fixture(autouse=True)
async def _reset_global_provider_verification_state(db_available: bool) -> None:
    """Same reset this module's other test file already documented as
    necessary: `AIProviderVerification` is deliberately not
    customer-scoped, so it isn't isolated by a fresh uuid4() customer_id
    the way every tenant-scoped table in this suite is."""
    async with async_session_factory() as session, session.begin():
        await session.execute(delete(AIProviderVerification))


async def test_two_concurrent_enable_toggles_for_the_same_customer_and_provider_both_succeed(
    db_available: bool,
) -> None:
    """Race-safe upsert (begin_nested/IntegrityError, same shape as
    ai_preference_service/notification_service/kill_switch_service):
    unlike those, no test had ever forced two concurrent callers to race
    the INSERT for CustomerAIProviderSetting."""
    customer_id = uuid.uuid4()

    async def toggle(enabled: bool) -> bool:
        async with tenant_scoped_session(customer_id) as db:
            setting = await set_provider_enabled_for_customer(
                db, customer_id=customer_id, provider=Provider.CLAUDE, enabled=enabled
            )
            await db.commit()
            return setting.enabled

    results = await asyncio.gather(toggle(True), toggle(False))
    assert set(results) == {True, False}  # each caller's own intended value, no raw IntegrityError

    async with tenant_scoped_session(customer_id) as db:
        assert (
            await is_provider_enabled_for_customer(db, customer_id=customer_id, provider=Provider.CLAUDE)
        ) in (
            True,
            False,
        )


async def test_setting_an_already_set_provider_toggle_updates_the_existing_row_not_a_duplicate(
    db_available: bool,
) -> None:
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as db:
        await set_provider_enabled_for_customer(
            db, customer_id=customer_id, provider=Provider.OPENAI, enabled=False
        )
        await db.commit()

    async with tenant_scoped_session(customer_id) as db:
        updated = await set_provider_enabled_for_customer(
            db, customer_id=customer_id, provider=Provider.OPENAI, enabled=True
        )
        await db.commit()
    assert updated.enabled is True

    async with tenant_scoped_session(customer_id) as db:
        assert (
            await is_provider_enabled_for_customer(db, customer_id=customer_id, provider=Provider.OPENAI)
            is True
        )


async def test_two_concurrent_fallback_toggles_for_the_same_customer_both_succeed(db_available: bool) -> None:
    customer_id = uuid.uuid4()

    async def toggle(enabled: bool) -> bool:
        async with tenant_scoped_session(customer_id) as db:
            setting = await set_fallback_enabled_for_customer(db, customer_id=customer_id, enabled=enabled)
            await db.commit()
            return setting.enabled

    results = await asyncio.gather(toggle(True), toggle(False))
    assert set(results) == {True, False}


async def test_setting_an_already_set_fallback_toggle_updates_the_existing_row_not_a_duplicate(
    db_available: bool,
) -> None:
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as db:
        await set_fallback_enabled_for_customer(db, customer_id=customer_id, enabled=True)
        await db.commit()

    async with tenant_scoped_session(customer_id) as db:
        updated = await set_fallback_enabled_for_customer(db, customer_id=customer_id, enabled=False)
        await db.commit()
    assert updated.enabled is False

    async with tenant_scoped_session(customer_id) as db:
        assert await is_fallback_enabled_for_customer(db, customer_id=customer_id) is False


async def test_two_concurrent_verification_records_for_the_same_provider_both_succeed(
    db_available: bool,
) -> None:
    """AIProviderVerification isn't tenant-scoped (no customer_id — see
    its own model docstring), so this race uses plain, independent
    sessions the same way test_identity_service.py's concurrent-first-
    login test does: a concurrent INSERT against the same primary key
    blocks at the database level, so asyncio.gather reliably exercises
    the begin_nested()/IntegrityError catch every time."""

    async def record(ok: bool) -> bool:
        async with async_session_factory() as db, db.begin():
            row = await record_provider_verification(
                db, provider=Provider.GEMINI, ok=ok, error_type=None, error_message=None
            )
            return row.last_verified_ok

    results = await asyncio.gather(record(True), record(False))
    assert set(results) == {True, False}

    async with async_session_factory() as db:
        status = await get_verification_status(db, provider=Provider.GEMINI)
    assert status is not None


async def test_recording_a_second_verification_for_the_same_provider_updates_the_existing_row(
    db_available: bool,
) -> None:
    async with async_session_factory() as db, db.begin():
        await record_provider_verification(
            db, provider=Provider.OPENAI, ok=True, error_type=None, error_message=None
        )

    async with async_session_factory() as db, db.begin():
        second = await record_provider_verification(
            db, provider=Provider.OPENAI, ok=False, error_type="ModelProviderError", error_message="boom"
        )
    assert second.last_verified_ok is False
    assert second.last_error_type == "ModelProviderError"

    async with async_session_factory() as db:
        status = await get_verification_status(db, provider=Provider.OPENAI)
    assert status is not None
    assert status.last_verified_ok is False


async def test_pick_fallback_provider_skips_unconfigured_and_disabled_candidates_in_order(
    db_available: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    customer_id = uuid.uuid4()
    settings = Settings()

    # OPENAI is excluded (the one that just failed). Of the remaining
    # FALLBACK_ORDER candidates (CLAUDE, GEMINI): CLAUDE is configured
    # but this customer has explicitly disabled it, GEMINI is configured
    # and enabled — so GEMINI must be the one returned, having skipped
    # CLAUDE for being disabled (not for being unconfigured).
    monkeypatch.setattr(
        "doda.application.ai_provider_settings_service.is_provider_configured",
        lambda provider, s: provider in (Provider.CLAUDE, Provider.GEMINI),
    )
    async with tenant_scoped_session(customer_id) as db:
        await set_provider_enabled_for_customer(
            db, customer_id=customer_id, provider=Provider.CLAUDE, enabled=False
        )
        await db.commit()

    async with tenant_scoped_session(customer_id) as db:
        chosen = await pick_fallback_provider(
            db, customer_id=customer_id, excluding=Provider.OPENAI, settings=settings
        )
    assert chosen is Provider.GEMINI


async def test_pick_fallback_provider_returns_none_when_no_eligible_candidate_exists(
    db_available: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    customer_id = uuid.uuid4()
    settings = Settings()
    # Nothing besides the excluded provider is configured at all.
    monkeypatch.setattr(
        "doda.application.ai_provider_settings_service.is_provider_configured",
        lambda provider, s: provider is Provider.OPENAI,
    )

    async with tenant_scoped_session(customer_id) as db:
        chosen = await pick_fallback_provider(
            db, customer_id=customer_id, excluding=Provider.OPENAI, settings=settings
        )
    assert chosen is None


class _SucceedsOnce:
    async def stream_chat(self, **kwargs: object) -> typing.AsyncIterator[GatewayEvent]:
        yield TextDelta(text="OK")


class _AlwaysFails:
    async def stream_chat(self, **kwargs: object) -> typing.AsyncIterator[GatewayEvent]:
        if False:
            yield  # pragma: no cover — makes this a real async generator function
        raise ModelProviderError("upstream 500", status_code=500)


async def test_testing_a_configured_provider_that_succeeds_reports_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "doda.application.ai_provider_settings_service.is_provider_configured",
        lambda provider, settings: True,
    )
    monkeypatch.setattr(
        "doda.application.ai_provider_settings_service.get_gateway",
        lambda provider, settings: _SucceedsOnce(),
    )

    ok, error_type, error_message = await ai_provider_settings_service.test_provider_connection(
        Provider.OPENAI, get_settings()
    )
    assert ok is True
    assert error_type is None
    assert error_message is None


async def test_testing_a_configured_provider_that_fails_reports_the_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "doda.application.ai_provider_settings_service.is_provider_configured",
        lambda provider, settings: True,
    )
    monkeypatch.setattr(
        "doda.application.ai_provider_settings_service.get_gateway", lambda provider, settings: _AlwaysFails()
    )

    ok, error_type, error_message = await ai_provider_settings_service.test_provider_connection(
        Provider.OPENAI, get_settings()
    )
    assert ok is False
    assert error_type == "ModelProviderError"
    assert error_message == "upstream 500"
