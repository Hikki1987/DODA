"""HTTP tests for the AI provider settings surface (ADR-009's settings
gap) — same authoritative-chain pattern as every other endpoint. No real
provider credential is configured in this test environment, so every
`configured`/`test-connection` result below reflects that honestly
(configured=False, test-connection ok=False) rather than a real
provider's actual availability.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from doda.db import async_session_factory
from doda.domain.ai_provider_settings.models import AIProviderVerification
from doda.main import app
from tests.integration.conftest import seed_workspace_member


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
async def _reset_global_provider_verification_state(db_available: bool) -> None:
    """`AIProviderVerification` is deliberately NOT customer-scoped (see
    its own model docstring — the credential is server-wide, so whether
    it works is a server-wide fact) — which means, unlike every
    tenant-scoped table elsewhere in this codebase, a fresh
    `uuid.uuid4()` customer per test does NOT isolate it: one test's
    test-connection result is visible to every other test's (and every
    future run's) `GET .../ai-providers`. Reset it before each test here,
    the same "don't leave state for the next test" discipline already
    applied to the outbox PEL probe (XDEL) and the E2E specs' per-spec
    seed prefixes — proven real by running the full suite: without this,
    `test_any_member_can_list_provider_statuses_but_not_modify_them`
    fails whenever it runs after `test_testing_an_unconfigured_
    provider_honestly_reports_failure_and_is_recorded` in the same
    process, exactly as it did the first time this file was written."""
    async with async_session_factory() as session, session.begin():
        await session.execute(delete(AIProviderVerification))


def _auth_headers(session_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_id}"}


async def test_any_member_can_list_provider_statuses_but_not_modify_them(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member(customer_role="member")

    listed = await client.get(
        f"/v1/customers/{member.customer_id}/ai-providers", headers=_auth_headers(member.session_id)
    )
    assert listed.status_code == 200
    statuses = {row["provider"]: row for row in listed.json()}
    assert set(statuses) == {"OPENAI", "GEMINI", "CLAUDE"}
    for row in statuses.values():
        assert row["configured"] is False  # no provider key in this test environment
        assert row["enabled"] is True  # row absence = enabled, by convention
        assert row["verified_at"] is None

    denied = await client.put(
        f"/v1/customers/{member.customer_id}/ai-providers/GEMINI/enabled",
        json={"enabled": False},
        headers=_auth_headers(member.session_id),
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "DENY"


async def test_customer_owner_can_disable_and_re_enable_a_provider(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member(customer_role="customer_owner")

    disable = await client.put(
        f"/v1/customers/{member.customer_id}/ai-providers/CLAUDE/enabled",
        json={"enabled": False},
        headers=_auth_headers(member.session_id),
    )
    assert disable.status_code == 200
    assert disable.json()["enabled"] is False

    listed = await client.get(
        f"/v1/customers/{member.customer_id}/ai-providers", headers=_auth_headers(member.session_id)
    )
    by_provider = {row["provider"]: row for row in listed.json()}
    assert by_provider["CLAUDE"]["enabled"] is False
    assert by_provider["OPENAI"]["enabled"] is True  # unaffected

    re_enable = await client.put(
        f"/v1/customers/{member.customer_id}/ai-providers/CLAUDE/enabled",
        json={"enabled": True},
        headers=_auth_headers(member.session_id),
    )
    assert re_enable.status_code == 200
    assert re_enable.json()["enabled"] is True


async def test_testing_an_unconfigured_provider_honestly_reports_failure_and_is_recorded(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member(customer_role="customer_owner")

    result = await client.post(
        f"/v1/customers/{member.customer_id}/ai-providers/OPENAI/test-connection",
        headers=_auth_headers(member.session_id),
    )
    assert result.status_code == 200
    assert result.json()["ok"] is False
    assert result.json()["error"] is not None

    listed = await client.get(
        f"/v1/customers/{member.customer_id}/ai-providers", headers=_auth_headers(member.session_id)
    )
    by_provider = {row["provider"]: row for row in listed.json()}
    assert by_provider["OPENAI"]["verified_ok"] is False
    assert by_provider["OPENAI"]["verified_at"] is not None


async def test_my_ai_preference_round_trips_and_a_plain_member_may_set_their_own(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member(customer_role="member")

    empty = await client.get(
        f"/v1/customers/{member.customer_id}/me/ai-preference", headers=_auth_headers(member.session_id)
    )
    assert empty.status_code == 200
    assert empty.json() == {"provider": None, "model": None}

    set_result = await client.put(
        f"/v1/customers/{member.customer_id}/me/ai-preference",
        json={"provider": "GEMINI", "model": "gemini-3.1-flash-lite"},
        headers=_auth_headers(member.session_id),
    )
    assert set_result.status_code == 200
    assert set_result.json() == {"provider": "GEMINI", "model": "gemini-3.1-flash-lite"}

    read_back = await client.get(
        f"/v1/customers/{member.customer_id}/me/ai-preference", headers=_auth_headers(member.session_id)
    )
    assert read_back.json() == {"provider": "GEMINI", "model": "gemini-3.1-flash-lite"}

    cleared = await client.delete(
        f"/v1/customers/{member.customer_id}/me/ai-preference", headers=_auth_headers(member.session_id)
    )
    assert cleared.status_code == 204

    after_clear = await client.get(
        f"/v1/customers/{member.customer_id}/me/ai-preference", headers=_auth_headers(member.session_id)
    )
    assert after_clear.json() == {"provider": None, "model": None}


async def test_workspace_ai_preference_requires_workspace_admin_to_set_but_not_to_read(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member(workspace_role="member")

    denied = await client.put(
        f"/v1/workspaces/{member.workspace_id}/ai-preference",
        json={"provider": "CLAUDE", "model": None},
        headers=_auth_headers(member.session_id),
    )
    assert denied.status_code == 403

    read_as_member = await client.get(
        f"/v1/workspaces/{member.workspace_id}/ai-preference", headers=_auth_headers(member.session_id)
    )
    assert read_as_member.status_code == 200
    assert read_as_member.json() == {"provider": None, "model": None}

    admin = await seed_workspace_member(workspace_role="workspace_admin")
    allowed = await client.put(
        f"/v1/workspaces/{admin.workspace_id}/ai-preference",
        json={"provider": "CLAUDE", "model": None},
        headers=_auth_headers(admin.session_id),
    )
    assert allowed.status_code == 200
    assert allowed.json()["provider"] == "CLAUDE"


async def test_fallback_setting_defaults_to_off_and_only_a_customer_owner_can_turn_it_on(
    client: AsyncClient, db_available: bool
) -> None:
    member = await seed_workspace_member(customer_role="member")

    default = await client.get(
        f"/v1/customers/{member.customer_id}/ai-fallback", headers=_auth_headers(member.session_id)
    )
    assert default.status_code == 200
    assert default.json() == {"enabled": False}

    denied = await client.put(
        f"/v1/customers/{member.customer_id}/ai-fallback",
        json={"enabled": True},
        headers=_auth_headers(member.session_id),
    )
    assert denied.status_code == 403

    owner = await seed_workspace_member(customer_role="customer_owner")
    allowed = await client.put(
        f"/v1/customers/{owner.customer_id}/ai-fallback",
        json={"enabled": True},
        headers=_auth_headers(owner.session_id),
    )
    assert allowed.status_code == 200
    assert allowed.json() == {"enabled": True}
