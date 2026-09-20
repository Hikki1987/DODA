"""`ai_budget_service.get_usage_report` and its HTTP surface
(`GET /v1/customers/{id}/ai-usage-report`) — NFR-COST-001's breakdown
half of "Customer/workspace/model bo'yicha... FinOps dashboard". The
budget/alert half (`get_ai_budget_status`) already showed one
customer-wide total; this shows where that spend actually went, same
"backend data exists, nothing surfaces it" pattern closed elsewhere in
this codebase (see CLAUDE.md)."""

import uuid
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient

from doda.application.ai_budget_service import current_year_month, get_usage_report
from doda.db import tenant_scoped_session
from doda.domain.ai_usage.models import AIUsageEvent, UsageEventStatus, UsageMode, UsageProvider
from doda.main import app
from tests.integration.conftest import seed_workspace_member


async def _add_usage_event(
    *,
    customer_id: uuid.UUID,
    workspace_id: uuid.UUID,
    provider: UsageProvider = UsageProvider.OPENAI,
    model: str = "gpt-test",
    actual_cost_cents: int = 100,
    status: UsageEventStatus = UsageEventStatus.RECONCILED,
    created_at: datetime | None = None,
) -> None:
    async with tenant_scoped_session(customer_id) as session:
        event = AIUsageEvent(
            customer_id=customer_id,
            workspace_id=workspace_id,
            conversation_id=None,
            trace_id=uuid.uuid4(),
            actor_id="user:test",
            provider=provider,
            mode=UsageMode.STANDARD,
            model=model,
            estimated_cost_cents=actual_cost_cents,
            actual_cost_cents=actual_cost_cents,
            status=status,
        )
        session.add(event)
        await session.flush()
        if created_at is not None:
            # created_at is CreatedAtMixin's Python-side default (set at
            # flush time); overriding it on the already-flushed object and
            # committing again is how this backdates a row for the
            # "different month is excluded" test below.
            event.created_at = created_at
        await session.commit()


async def test_usage_report_sums_multiple_events_for_the_same_workspace_provider_model(
    db_available: bool,
) -> None:
    member = await seed_workspace_member()
    await _add_usage_event(
        customer_id=member.customer_id, workspace_id=member.workspace_id, actual_cost_cents=150
    )
    await _add_usage_event(
        customer_id=member.customer_id, workspace_id=member.workspace_id, actual_cost_cents=250
    )

    async with tenant_scoped_session(member.customer_id) as session:
        rows = await get_usage_report(
            session, customer_id=member.customer_id, year_month=current_year_month()
        )

    assert len(rows) == 1
    assert rows[0].workspace_id == member.workspace_id
    assert rows[0].workspace_name == "Test Workspace"
    assert rows[0].cost_cents == 400
    assert rows[0].event_count == 2


async def test_usage_report_keeps_different_models_as_separate_rows(db_available: bool) -> None:
    member = await seed_workspace_member()
    await _add_usage_event(
        customer_id=member.customer_id, workspace_id=member.workspace_id, model="gpt-a", actual_cost_cents=100
    )
    await _add_usage_event(
        customer_id=member.customer_id, workspace_id=member.workspace_id, model="gpt-b", actual_cost_cents=900
    )

    async with tenant_scoped_session(member.customer_id) as session:
        rows = await get_usage_report(
            session, customer_id=member.customer_id, year_month=current_year_month()
        )

    assert len(rows) == 2
    # Ordered by cost descending.
    assert rows[0].model == "gpt-b"
    assert rows[0].cost_cents == 900
    assert rows[1].model == "gpt-a"
    assert rows[1].cost_cents == 100


async def test_usage_report_excludes_a_different_customers_events(db_available: bool) -> None:
    member_a = await seed_workspace_member()
    member_b = await seed_workspace_member()
    await _add_usage_event(customer_id=member_a.customer_id, workspace_id=member_a.workspace_id)
    await _add_usage_event(customer_id=member_b.customer_id, workspace_id=member_b.workspace_id)

    async with tenant_scoped_session(member_a.customer_id) as session:
        rows = await get_usage_report(
            session, customer_id=member_a.customer_id, year_month=current_year_month()
        )

    assert len(rows) == 1
    assert rows[0].workspace_id == member_a.workspace_id


async def test_usage_report_excludes_a_non_reconciled_event(db_available: bool) -> None:
    member = await seed_workspace_member()
    await _add_usage_event(
        customer_id=member.customer_id, workspace_id=member.workspace_id, status=UsageEventStatus.RESERVED
    )

    async with tenant_scoped_session(member.customer_id) as session:
        rows = await get_usage_report(
            session, customer_id=member.customer_id, year_month=current_year_month()
        )

    assert rows == []


async def test_usage_report_excludes_an_event_from_a_different_month(db_available: bool) -> None:
    member = await seed_workspace_member()
    await _add_usage_event(
        customer_id=member.customer_id,
        workspace_id=member.workspace_id,
        created_at=datetime(2020, 1, 15, tzinfo=UTC),
    )

    async with tenant_scoped_session(member.customer_id) as session:
        rows = await get_usage_report(
            session, customer_id=member.customer_id, year_month=current_year_month()
        )
        rows_2020_01 = await get_usage_report(session, customer_id=member.customer_id, year_month="2020-01")

    assert rows == []
    assert len(rows_2020_01) == 1


async def test_ai_usage_report_api_denies_a_plain_member_but_allows_owner_and_auditor(
    db_available: bool,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        member = await seed_workspace_member(customer_role="member")
        denied = await client.get(
            f"/v1/customers/{member.customer_id}/ai-usage-report",
            headers={"Authorization": f"Bearer {member.session_id}"},
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == "DENY"

        owner = await seed_workspace_member(customer_role="customer_owner")
        await _add_usage_event(
            customer_id=owner.customer_id,
            workspace_id=owner.workspace_id,
            provider=UsageProvider.CLAUDE,
            model="claude-test",
            actual_cost_cents=1234,
        )

        owner_response = await client.get(
            f"/v1/customers/{owner.customer_id}/ai-usage-report",
            headers={"Authorization": f"Bearer {owner.session_id}"},
        )
        assert owner_response.status_code == 200
        body = owner_response.json()
        assert len(body) == 1
        assert body[0]["workspace_name"] == "Test Workspace"
        assert body[0]["provider"] == "CLAUDE"
        assert body[0]["model"] == "claude-test"
        assert body[0]["cost_usd"] == 12.34
        assert body[0]["event_count"] == 1

        auditor = await seed_workspace_member(customer_role="auditor")
        auditor_response = await client.get(
            f"/v1/customers/{auditor.customer_id}/ai-usage-report",
            headers={"Authorization": f"Bearer {auditor.session_id}"},
        )
        assert auditor_response.status_code == 200
        assert auditor_response.json() == []


async def test_ai_usage_report_rejects_a_malformed_year_month(db_available: bool) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        owner = await seed_workspace_member(customer_role="customer_owner")
        response = await client.get(
            f"/v1/customers/{owner.customer_id}/ai-usage-report",
            params={"year_month": "not-a-month"},
            headers={"Authorization": f"Bearer {owner.session_id}"},
        )
        assert response.status_code == 422
