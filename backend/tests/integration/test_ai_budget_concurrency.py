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
