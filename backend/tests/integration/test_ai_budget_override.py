"""FR-ADM-005 ("AI byudjeti va limitlarni belgilash") — a per-customer
override of the deployment-wide default soft/hard AI budget caps.
`test_ai_budget_status.py` already covers the un-overridden default
path; these tests cover the override itself (application layer + HTTP)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from doda.ai.errors import BudgetExceededError
from doda.application.ai_budget_service import (
    InvalidBudgetOverrideError,
    get_budget_status,
    reserve_budget,
    set_customer_ai_budget_override,
)
from doda.db import tenant_scoped_session
from doda.main import app
from tests.integration.conftest import seed_workspace_member


async def test_setting_an_override_changes_the_effective_caps(db_available: bool) -> None:
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        await set_customer_ai_budget_override(
            session, customer_id=customer_id, actor_id="user:test", soft_cap_usd=5.0, hard_cap_usd=10.0
        )
        await session.commit()

    async with tenant_scoped_session(customer_id) as session:
        status = await get_budget_status(session, customer_id=customer_id)

    assert status.soft_cap_cents == 500
    assert status.hard_cap_cents == 1000


async def test_the_override_is_enforced_not_just_reported(db_available: bool) -> None:
    """A stricter override actually blocks a request the default caps
    would have admitted — proving reserve_budget reads the SAME override
    get_budget_status reports, not a display-only value."""
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        await set_customer_ai_budget_override(
            session, customer_id=customer_id, actor_id="user:test", soft_cap_usd=0.01, hard_cap_usd=0.02
        )
        await session.commit()

    async with tenant_scoped_session(customer_id) as session:
        with pytest.raises(BudgetExceededError):
            await reserve_budget(session, customer_id=customer_id, estimated_cost_cents=5)


async def test_a_hard_cap_below_the_soft_cap_is_rejected(db_available: bool) -> None:
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        with pytest.raises(InvalidBudgetOverrideError):
            await set_customer_ai_budget_override(
                session, customer_id=customer_id, actor_id="user:test", soft_cap_usd=50.0, hard_cap_usd=10.0
            )


async def test_a_non_positive_cap_is_rejected(db_available: bool) -> None:
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        with pytest.raises(InvalidBudgetOverrideError):
            await set_customer_ai_budget_override(
                session, customer_id=customer_id, actor_id="user:test", soft_cap_usd=0.0, hard_cap_usd=10.0
            )


async def test_setting_it_twice_replaces_the_value_not_duplicates_the_row(db_available: bool) -> None:
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        await set_customer_ai_budget_override(
            session, customer_id=customer_id, actor_id="user:test", soft_cap_usd=5.0, hard_cap_usd=10.0
        )
        await session.commit()

    async with tenant_scoped_session(customer_id) as session:
        await set_customer_ai_budget_override(
            session, customer_id=customer_id, actor_id="user:test", soft_cap_usd=15.0, hard_cap_usd=30.0
        )
        await session.commit()

    async with tenant_scoped_session(customer_id) as session:
        status = await get_budget_status(session, customer_id=customer_id)
    assert status.soft_cap_cents == 1500
    assert status.hard_cap_cents == 3000


async def test_http_get_and_set_budget_limits(db_available: bool) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        member = await seed_workspace_member(customer_role="member")
        denied_get = await client.get(
            f"/v1/customers/{member.customer_id}/ai-budget-limits",
            headers={"Authorization": f"Bearer {member.session_id}"},
        )
        assert denied_get.status_code == 403

        owner = await seed_workspace_member(customer_role="customer_owner")

        # No override yet — both fields are None (deployment default applies).
        default_view = await client.get(
            f"/v1/customers/{owner.customer_id}/ai-budget-limits",
            headers={"Authorization": f"Bearer {owner.session_id}"},
        )
        assert default_view.status_code == 200
        assert default_view.json() == {"soft_cap_usd": None, "hard_cap_usd": None}

        denied_set = await client.put(
            f"/v1/customers/{member.customer_id}/ai-budget-limits",
            json={"soft_cap_usd": 5.0, "hard_cap_usd": 10.0},
            headers={"Authorization": f"Bearer {member.session_id}"},
        )
        assert denied_set.status_code == 403

        invalid_set = await client.put(
            f"/v1/customers/{owner.customer_id}/ai-budget-limits",
            json={"soft_cap_usd": 50.0, "hard_cap_usd": 10.0},
            headers={"Authorization": f"Bearer {owner.session_id}"},
        )
        assert invalid_set.status_code == 422
        assert invalid_set.json()["code"] == "INVALID_BUDGET_LIMITS"

        owner_set = await client.put(
            f"/v1/customers/{owner.customer_id}/ai-budget-limits",
            json={"soft_cap_usd": 5.0, "hard_cap_usd": 10.0},
            headers={"Authorization": f"Bearer {owner.session_id}"},
        )
        assert owner_set.status_code == 200
        assert owner_set.json() == {"soft_cap_usd": 5.0, "hard_cap_usd": 10.0}

        # The effective status endpoint now reports the override.
        effective = await client.get(
            f"/v1/customers/{owner.customer_id}/ai-budget",
            headers={"Authorization": f"Bearer {owner.session_id}"},
        )
        assert effective.json()["soft_cap_usd"] == 5.0
        assert effective.json()["hard_cap_usd"] == 10.0

        # Auditor can view the override, not change it.
        auditor = await seed_workspace_member(customer_role="auditor")
        auditor_view = await client.get(
            f"/v1/customers/{auditor.customer_id}/ai-budget-limits",
            headers={"Authorization": f"Bearer {auditor.session_id}"},
        )
        assert auditor_view.status_code == 200
        auditor_denied_set = await client.put(
            f"/v1/customers/{auditor.customer_id}/ai-budget-limits",
            json={"soft_cap_usd": 1.0, "hard_cap_usd": 2.0},
            headers={"Authorization": f"Bearer {auditor.session_id}"},
        )
        assert auditor_denied_set.status_code == 403

        denied_delete = await client.delete(
            f"/v1/customers/{member.customer_id}/ai-budget-limits",
            headers={"Authorization": f"Bearer {member.session_id}"},
        )
        assert denied_delete.status_code == 403

        cleared = await client.delete(
            f"/v1/customers/{owner.customer_id}/ai-budget-limits",
            headers={"Authorization": f"Bearer {owner.session_id}"},
        )
        assert cleared.status_code == 204

        after_clear = await client.get(
            f"/v1/customers/{owner.customer_id}/ai-budget-limits",
            headers={"Authorization": f"Bearer {owner.session_id}"},
        )
        assert after_clear.json() == {"soft_cap_usd": None, "hard_cap_usd": None}
