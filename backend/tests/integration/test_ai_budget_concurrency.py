"""Proves ai_budget_service.reserve_budget's SELECT ... FOR UPDATE lock
actually serializes two concurrent reservations for the same customer —
without it, both could read the ledger before either commits and both
pass the hard-cap check, letting concurrent requests jointly exceed the
monthly budget (exactly the instruction: "bir vaqtning o'zida kelgan
so'rovlar budjet cheklovini chetlab o'tmasin").

Same forced-interleaving technique as
test_kill_switch_engage_concurrency.py/test_last_owner_invariant_
concurrency.py: two sessions read the ledger row before either commits.
Chosen estimate (5000 cents) fits the default hard cap (8000 cents =
$80, doda.config.Settings.ai_budget_hard_usd_per_customer_month) alone
but not twice — no settings override needed.
"""

import asyncio
import uuid

from sqlalchemy import select

from doda.ai.errors import BudgetExceededError
from doda.application.ai_budget_service import current_year_month, reserve_budget
from doda.db import tenant_scoped_session
from doda.domain.ai_usage.models import AIBudgetLedger
from tests.integration.conftest import race_outcome, two_racing_sessions

ESTIMATE_CENTS = 5000  # fits the $80 default cap once, not twice


async def test_two_concurrent_reservations_cannot_jointly_exceed_the_hard_cap(db_available: bool) -> None:
    customer_id = uuid.uuid4()

    # Seed (and commit) an existing ledger row at 0 first — the race must
    # be a read-then-write on an EXISTING row. An insert race (no row
    # yet) would be serialized by Postgres's own unique index regardless
    # of this module's explicit locking, and would prove nothing about
    # it. ESTIMATE_CENTS (5000) fits the $80 default cap (8000 cents)
    # once; twice (10000) does not.
    async with tenant_scoped_session(customer_id) as setup_session:
        setup_session.add(AIBudgetLedger(customer_id=customer_id, year_month=current_year_month()))
        await setup_session.commit()

    cm1, session1, cm2, session2 = await two_racing_sessions(customer_id)

    outcomes = await asyncio.gather(
        race_outcome(
            cm1,
            reserve_budget(session1, customer_id=customer_id, estimated_cost_cents=ESTIMATE_CENTS),
            expected_exc=BudgetExceededError,
        ),
        race_outcome(
            cm2,
            reserve_budget(session2, customer_id=customer_id, estimated_cost_cents=ESTIMATE_CENTS),
            expected_exc=BudgetExceededError,
        ),
    )

    assert sorted(outcomes) == ["ok", "rejected"]

    async with tenant_scoped_session(customer_id) as session:
        ledger = await session.get(AIBudgetLedger, (customer_id, current_year_month()))
        assert ledger is not None
        # Only the winner's reservation landed — not both (which would be
        # 10000, double-booking the budget).
        assert ledger.reserved_cents == ESTIMATE_CENTS


async def test_two_concurrent_first_reservations_for_a_brand_new_customer_month_both_land(
    db_available: bool,
) -> None:
    """The OTHER race `_get_or_create_locked_ledger` guards against: no
    ledger row exists yet for this (customer, month) at all, so both
    callers race the INSERT itself (begin_nested/IntegrityError), not a
    read-then-write on an existing row (that's the test above). Same
    reasoning as test_identity_service.py's concurrent-first-login test:
    a concurrent INSERT against the same primary key blocks at the
    database level, so plain asyncio.gather (no forced interleaving)
    reliably exercises it — and unlike the hard-cap race above, both
    reservations here fit comfortably under the cap, so both must
    succeed and their estimates must both land (summed), not just one."""
    customer_id = uuid.uuid4()

    async def reserve(estimate: int) -> None:
        async with tenant_scoped_session(customer_id) as db:
            await reserve_budget(db, customer_id=customer_id, estimated_cost_cents=estimate)
            await db.commit()

    await asyncio.gather(reserve(100), reserve(200))

    async with tenant_scoped_session(customer_id) as session:
        rows = list(
            (
                await session.execute(select(AIBudgetLedger).where(AIBudgetLedger.customer_id == customer_id))
            ).scalars()
        )
    assert len(rows) == 1  # exactly one ledger row for this (customer, month) — not two
    assert rows[0].reserved_cents == 300  # both estimates landed, neither lost to the race
