"""`ai_budget_service.get_budget_status` and its HTTP surface
(`GET /v1/customers/{id}/ai-budget`) — NFR-COST-001's "byudjet va alert",
which had a computation (`is_over_soft_budget`) but no way for anyone to
ever see it before this. See CLAUDE.md for the "backend capability
exists, nothing surfaces it" pattern this closes."""

import uuid

from httpx import ASGITransport, AsyncClient

from doda.application.ai_budget_service import current_year_month, get_budget_status
from doda.db import tenant_scoped_session
from doda.domain.ai_usage.models import AIBudgetLedger
from doda.main import app
from tests.integration.conftest import seed_workspace_member


async def test_get_budget_status_with_no_ledger_row_reports_zero_spend(db_available: bool) -> None:
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        status = await get_budget_status(session, customer_id=customer_id)

    assert status.spent_cents == 0
    assert status.over_soft_budget is False
    assert status.hard_cap_cents > status.soft_cap_cents


async def test_get_budget_status_reflects_reserved_and_actual_cents(db_available: bool) -> None:
    customer_id = uuid.uuid4()
    async with tenant_scoped_session(customer_id) as session:
        session.add(
            AIBudgetLedger(
                customer_id=customer_id,
                year_month=current_year_month(),
                reserved_cents=100,
                actual_cents=2500,
            )
        )
        await session.commit()

    async with tenant_scoped_session(customer_id) as session:
        status = await get_budget_status(session, customer_id=customer_id)

    assert status.spent_cents == 2600
    # Default soft cap is $20 (2000 cents) — 2600 is over it.
    assert status.over_soft_budget is True


async def test_ai_budget_api_denies_a_plain_member_but_allows_owner_and_auditor(db_available: bool) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        member = await seed_workspace_member(customer_role="member")
        denied = await client.get(
            f"/v1/customers/{member.customer_id}/ai-budget",
            headers={"Authorization": f"Bearer {member.session_id}"},
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == "DENY"

        owner = await seed_workspace_member(customer_role="customer_owner")
        async with tenant_scoped_session(owner.customer_id) as session:
            session.add(
                AIBudgetLedger(
                    customer_id=owner.customer_id, year_month=current_year_month(), actual_cents=500
                )
            )
            await session.commit()

        owner_response = await client.get(
            f"/v1/customers/{owner.customer_id}/ai-budget",
            headers={"Authorization": f"Bearer {owner.session_id}"},
        )
        assert owner_response.status_code == 200
        body = owner_response.json()
        assert body["spent_usd"] == 5.0
        assert body["over_soft_budget"] is False
        assert body["soft_cap_usd"] == 20.0
        assert body["hard_cap_usd"] == 80.0

        auditor = await seed_workspace_member(customer_role="auditor")
        auditor_response = await client.get(
            f"/v1/customers/{auditor.customer_id}/ai-budget",
            headers={"Authorization": f"Bearer {auditor.session_id}"},
        )
        assert auditor_response.status_code == 200
