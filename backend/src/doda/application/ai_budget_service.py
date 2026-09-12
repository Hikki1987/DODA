"""AI cost budget enforcement — NFR-COST-001, OD-008 ($20-$100/month
starting range), and the explicit instruction "bir vaqtning o'zida kelgan
so'rovlar budjet cheklovini chetlab o'tmasin" (concurrent requests must
not be able to bypass the cap).

Two-phase reserve/reconcile, because real cost isn't known until AFTER a
gateway call returns real token usage:

1. `reserve_budget` — called BEFORE any provider call, with an ESTIMATE
   (`doda.infrastructure.openai_pricing.estimate_cost_cents`, from input
   char count and the request's `max_output_tokens` ceiling). Locks the
   customer's current-month ledger row with `SELECT ... FOR UPDATE`
   first — the same proven pattern as `audit_chain_tips`,
   `workspace_kill_switches`, task-status/approval-consume concurrency
   fixes, and the last-owner invariant (see CLAUDE.md for all five). If
   the projected total would exceed the hard cap, raises
   `BudgetExceededError` and the caller must not proceed to call the
   provider at all.
2. `reconcile_budget` — called AFTER the call, with the real
   `GatewayUsage`-derived cost. Replaces the reservation with the actual
   figure on the same locked row.
3. `release_reservation` — called if the provider call failed before any
   real usage was billed (timeout, rate limit, network error): gives the
   estimate back rather than leaving it stuck as phantom spend.

This module makes no authorization decision about WHO may chat — that is
`authorize_use_chat` (authz_service.py), already enforced before any of
this runs. This only decides whether a customer's account can still
afford the call.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from doda.ai.errors import BudgetExceededError
from doda.ai.types import ChatMode, GatewayUsage, Provider
from doda.config import get_settings
from doda.domain.ai_usage.models import (
    AIBudgetLedger,
    AIUsageEvent,
    UsageEventStatus,
    UsageMode,
    UsageProvider,
)
from doda.domain.base import utcnow
from doda.infrastructure.ai_pricing import CENTS_PER_DOLLAR


def current_year_month() -> str:
    return utcnow().strftime("%Y-%m")


async def _get_or_create_locked_ledger(
    session: AsyncSession, *, customer_id: uuid.UUID, year_month: str
) -> AIBudgetLedger:
    ledger = await session.scalar(
        select(AIBudgetLedger)
        .where(AIBudgetLedger.customer_id == customer_id, AIBudgetLedger.year_month == year_month)
        .with_for_update()
    )
    if ledger is not None:
        return ledger

    ledger = AIBudgetLedger(customer_id=customer_id, year_month=year_month)
    try:
        async with session.begin_nested():
            session.add(ledger)
            await session.flush()
    except IntegrityError:
        # A concurrent caller created this month's row first — the insert
        # above rolled back on its own SAVEPOINT, so re-select now that
        # it exists; this SELECT ... FOR UPDATE blocks until the other
        # transaction commits, then sees the real row (same race shape as
        # kill_switch_service.engage_*_kill_switch).
        ledger = await session.scalar(
            select(AIBudgetLedger)
            .where(AIBudgetLedger.customer_id == customer_id, AIBudgetLedger.year_month == year_month)
            .with_for_update()
        )
        assert ledger is not None
    return ledger


async def reserve_budget(session: AsyncSession, *, customer_id: uuid.UUID, estimated_cost_cents: int) -> None:
    settings = get_settings()
    hard_cap_cents = round(settings.ai_budget_hard_usd_per_customer_month * CENTS_PER_DOLLAR)
    year_month = current_year_month()
    ledger = await _get_or_create_locked_ledger(session, customer_id=customer_id, year_month=year_month)

    projected_cents = ledger.reserved_cents + ledger.actual_cents + estimated_cost_cents
    if projected_cents > hard_cap_cents:
        raise BudgetExceededError(
            f"customer {customer_id} would exceed its ${settings.ai_budget_hard_usd_per_customer_month:.2f}"
            " monthly AI budget",
            scope="customer_month",
        )

    ledger.reserved_cents += estimated_cost_cents
    await session.flush()


async def is_over_soft_budget(session: AsyncSession, *, customer_id: uuid.UUID) -> bool:
    """Non-blocking warning check — the caller proceeds regardless, but
    may surface this to the user (e.g. "oylik byudjetning katta qismi
    sarflandi"). No locking needed: a stale read here costs nothing,
    unlike the hard-cap check in `reserve_budget`."""
    settings = get_settings()
    soft_cap_cents = round(settings.ai_budget_soft_usd_per_customer_month * CENTS_PER_DOLLAR)
    year_month = current_year_month()
    ledger = await session.scalar(
        select(AIBudgetLedger).where(
            AIBudgetLedger.customer_id == customer_id, AIBudgetLedger.year_month == year_month
        )
    )
    if ledger is None:
        return False
    return (ledger.reserved_cents + ledger.actual_cents) > soft_cap_cents


async def reconcile_budget(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    estimated_cost_cents: int,
    actual_cost_cents: int,
) -> None:
    year_month = current_year_month()
    ledger = await _get_or_create_locked_ledger(session, customer_id=customer_id, year_month=year_month)
    ledger.reserved_cents = max(0, ledger.reserved_cents - estimated_cost_cents)
    ledger.actual_cents += actual_cost_cents
    await session.flush()


async def release_reservation(
    session: AsyncSession, *, customer_id: uuid.UUID, estimated_cost_cents: int
) -> None:
    """Refund a reservation whose call never billed real usage (it failed
    or timed out before the provider returned anything)."""
    year_month = current_year_month()
    ledger = await _get_or_create_locked_ledger(session, customer_id=customer_id, year_month=year_month)
    ledger.reserved_cents = max(0, ledger.reserved_cents - estimated_cost_cents)
    await session.flush()


async def record_usage_event(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    trace_id: uuid.UUID,
    actor_id: str,
    provider: Provider,
    model: str,
    mode: ChatMode,
    usage: GatewayUsage,
    estimated_cost_cents: int,
    actual_cost_cents: int,
) -> AIUsageEvent:
    """NFR-COST-001's FinOps breakdown row — one per chat TURN (which may
    itself span several internal gateway calls across tool-call rounds;
    `usage`/`*_cost_cents` are already the SUM across all of them, so this
    never double-counts a turn's spend across multiple rows)."""
    event = AIUsageEvent(
        customer_id=customer_id,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        trace_id=trace_id,
        actor_id=actor_id,
        provider=UsageProvider(provider.value),
        mode=UsageMode(mode.value),
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        estimated_cost_cents=estimated_cost_cents,
        actual_cost_cents=actual_cost_cents,
        status=UsageEventStatus.RECONCILED,
    )
    session.add(event)
    await session.flush()
    return event
