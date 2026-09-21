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
2. `reconcile_budget` — called AFTER the call (success OR failure, with
   whatever real `GatewayUsage`-derived cost was actually incurred —
   zero if the provider never billed anything). Replaces the reservation
   with the actual figure on the same locked row, so a failure never
   leaves a phantom reservation permanently eating into the customer's
   budget for no real spend — `doda.application.conversation_service.
   stream_message`'s own exception handler is the one caller that relies
   on this for the failure case, pairing it with a REFUNDED-status
   `AIUsageEvent` (via `record_usage_event`) so the per-turn FinOps trail
   accounts for failed turns too, not just successful ones.

This module makes no authorization decision about WHO may chat — that is
`authorize_use_chat` (authz_service.py), already enforced before any of
this runs. This only decides whether a customer's account can still
afford the call.
"""

import dataclasses
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from doda.ai.errors import BudgetExceededError
from doda.ai.types import ChatMode, GatewayUsage, Provider
from doda.application.audit_service import record_audit_event
from doda.config import get_settings
from doda.domain.ai_usage.models import (
    AIBudgetLedger,
    AIUsageEvent,
    CustomerAIBudgetOverride,
    UsageEventStatus,
    UsageMode,
    UsageProvider,
)
from doda.domain.base import utcnow
from doda.domain.workspace.models import Workspace
from doda.infrastructure.ai_pricing import CENTS_PER_DOLLAR


class InvalidBudgetOverrideError(Exception):
    """Raised by set_customer_ai_budget_override for a non-positive cap
    or a hard cap below the soft cap — the latter isn't a data-integrity
    problem the DB itself would reject, but it would make the soft-cap
    warning (over_soft_budget) fire only AFTER the hard cap has already
    blocked the request, defeating the entire point of having two caps."""


def current_year_month() -> str:
    return utcnow().strftime("%Y-%m")


async def _effective_caps_cents(session: AsyncSession, *, customer_id: uuid.UUID) -> tuple[int, int]:
    """(soft_cap_cents, hard_cap_cents) — a per-customer override
    (FR-ADM-005) if one exists, otherwise the deployment-wide default
    from Settings. The one place both reserve_budget and
    get_budget_status resolve caps from, so they can never silently
    disagree about which value is authoritative for a given customer."""
    override = await session.get(CustomerAIBudgetOverride, customer_id)
    if override is not None:
        return override.soft_cap_cents, override.hard_cap_cents
    settings = get_settings()
    return (
        round(settings.ai_budget_soft_usd_per_customer_month * CENTS_PER_DOLLAR),
        round(settings.ai_budget_hard_usd_per_customer_month * CENTS_PER_DOLLAR),
    )


async def get_customer_ai_budget_override(
    session: AsyncSession, *, customer_id: uuid.UUID
) -> CustomerAIBudgetOverride | None:
    return await session.get(CustomerAIBudgetOverride, customer_id)


async def set_customer_ai_budget_override(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    actor_id: str,
    soft_cap_usd: float,
    hard_cap_usd: float,
) -> CustomerAIBudgetOverride:
    if soft_cap_usd <= 0 or hard_cap_usd <= 0:
        raise InvalidBudgetOverrideError("budget caps must be positive")
    if hard_cap_usd < soft_cap_usd:
        raise InvalidBudgetOverrideError("the hard cap must be at least as large as the soft cap")
    soft_cap_cents = round(soft_cap_usd * CENTS_PER_DOLLAR)
    hard_cap_cents = round(hard_cap_usd * CENTS_PER_DOLLAR)

    override = await session.get(CustomerAIBudgetOverride, customer_id)
    if override is None:
        override = CustomerAIBudgetOverride(
            customer_id=customer_id, soft_cap_cents=soft_cap_cents, hard_cap_cents=hard_cap_cents
        )
        try:
            async with session.begin_nested():
                session.add(override)
                await session.flush()
        except IntegrityError:
            # Two concurrent "set" calls for a customer with no override
            # yet both saw None and both tried to insert — same "last
            # write wins" recovery as notification_service.set_
            # notification_preference, for the same reason: each caller
            # has its own intended value, not a shared "ensure true".
            override = await session.get(CustomerAIBudgetOverride, customer_id)
            assert override is not None
            override.soft_cap_cents = soft_cap_cents
            override.hard_cap_cents = hard_cap_cents
            await session.flush()
    else:
        override.soft_cap_cents = soft_cap_cents
        override.hard_cap_cents = hard_cap_cents
        await session.flush()

    # FR-ADM-006's "o'zgarish darhol qo'llanadi va audit qilinadi" applies
    # in spirit to every admin config change in this codebase, this one
    # included — matches set_workspace_language's own "versioned AND
    # audited, not just one of the two" reasoning.
    await record_audit_event(
        session,
        customer_id=customer_id,
        trace_id=uuid.uuid4(),
        actor_id=actor_id,
        event_type="ai_budget.override_set.v1",
        safe_metadata={"soft_cap_usd": soft_cap_usd, "hard_cap_usd": hard_cap_usd},
    )
    return override


async def clear_customer_ai_budget_override(
    session: AsyncSession, *, customer_id: uuid.UUID, actor_id: str
) -> None:
    override = await session.get(CustomerAIBudgetOverride, customer_id)
    if override is not None:
        await session.delete(override)
        await session.flush()
        await record_audit_event(
            session,
            customer_id=customer_id,
            trace_id=uuid.uuid4(),
            actor_id=actor_id,
            event_type="ai_budget.override_cleared.v1",
            safe_metadata={},
        )


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
    _soft_cap_cents, hard_cap_cents = await _effective_caps_cents(session, customer_id=customer_id)
    year_month = current_year_month()
    ledger = await _get_or_create_locked_ledger(session, customer_id=customer_id, year_month=year_month)

    projected_cents = ledger.reserved_cents + ledger.actual_cents + estimated_cost_cents
    if projected_cents > hard_cap_cents:
        raise BudgetExceededError(
            f"customer {customer_id} would exceed its ${hard_cap_cents / CENTS_PER_DOLLAR:.2f}"
            " monthly AI budget",
            scope="customer_month",
        )

    ledger.reserved_cents += estimated_cost_cents
    await session.flush()


@dataclasses.dataclass(frozen=True)
class BudgetStatus:
    """NFR-COST-001's "byudjet va alert" — until `api/ai_settings.py`
    exposed this, nothing could ever surface it: a customer only
    discovered they were near/over budget when a real chat turn suddenly
    402'd with BudgetExceededError, with zero visibility beforehand. No
    locking needed to compute this — same "a stale read here costs
    nothing" reasoning this replaces (`is_over_soft_budget`, unused and
    untested before this)."""

    year_month: str
    soft_cap_cents: int
    hard_cap_cents: int
    spent_cents: int
    over_soft_budget: bool


def _month_bounds_utc(year_month: str) -> tuple[datetime, datetime]:
    """[start, end) UTC calendar-month bounds for the "YYYY-MM" string
    `AIBudgetLedger.year_month`/`current_year_month` already use — kept
    here rather than duplicated at the call site so the report's month
    filter and the ledger's own month key can never silently drift apart."""
    year, month = (int(part) for part in year_month.split("-"))
    start = datetime(year, month, 1, tzinfo=UTC)
    end = datetime(year + 1, 1, 1, tzinfo=UTC) if month == 12 else datetime(year, month + 1, 1, tzinfo=UTC)
    return start, end


@dataclasses.dataclass(frozen=True)
class UsageBreakdownRow:
    """One (workspace, provider, model) slice of a customer's monthly AI
    spend — NFR-COST-001's "Customer/workspace/model bo'yicha... FinOps
    dashboard" acceptance criterion, distinct from `BudgetStatus` (a
    single customer-wide total): the budget/alert half of this
    requirement was closed by OD-008 already, this closes the
    breakdown half. `AIUsageEvent` has carried every field this needs
    since it was first written for `conversation_service.stream_
    message` — nothing new to record, only to aggregate and expose."""

    workspace_id: uuid.UUID
    workspace_name: str
    provider: Provider
    model: str
    cost_cents: int
    event_count: int


async def get_usage_report(
    session: AsyncSession, *, customer_id: uuid.UUID, year_month: str
) -> list[UsageBreakdownRow]:
    """Only RECONCILED rows count — a still-open RESERVED row (none exist
    in practice; see `UsageEventStatus`'s own docstring) has no real
    `actual_cost_cents` yet, and REFUNDED rows already carry whatever
    real spend a failed/cancelled turn incurred (possibly zero) inside
    their own `actual_cost_cents`, so no separate REFUNDED branch is
    needed — summing them in is exactly right, not double-counting.

    Joins to Workspace for a display name (the same "raw UUIDs are
    meaningless to a human" reasoning `workspace_service.
    list_workspace_members` already applies to its own User join) —
    filtered by customer_id on BOTH sides of the join, not just
    `AIUsageEvent`'s, per 6.2's "no repository query without an explicit
    customer_id predicate" rule."""
    start, end = _month_bounds_utc(year_month)
    result = await session.execute(
        select(
            AIUsageEvent.workspace_id,
            Workspace.name,
            AIUsageEvent.provider,
            AIUsageEvent.model,
            func.sum(AIUsageEvent.actual_cost_cents),
            func.count(),
        )
        .join(Workspace, Workspace.id == AIUsageEvent.workspace_id)
        .where(
            AIUsageEvent.customer_id == customer_id,
            Workspace.customer_id == customer_id,
            AIUsageEvent.status == UsageEventStatus.RECONCILED,
            AIUsageEvent.created_at >= start,
            AIUsageEvent.created_at < end,
        )
        .group_by(AIUsageEvent.workspace_id, Workspace.name, AIUsageEvent.provider, AIUsageEvent.model)
        .order_by(func.sum(AIUsageEvent.actual_cost_cents).desc())
    )
    return [
        UsageBreakdownRow(
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            provider=Provider(provider.value),
            model=model,
            cost_cents=cost_cents or 0,
            event_count=event_count,
        )
        for workspace_id, workspace_name, provider, model, cost_cents, event_count in result.all()
    ]


async def get_budget_status(session: AsyncSession, *, customer_id: uuid.UUID) -> BudgetStatus:
    soft_cap_cents, hard_cap_cents = await _effective_caps_cents(session, customer_id=customer_id)
    year_month = current_year_month()
    ledger = await session.scalar(
        select(AIBudgetLedger).where(
            AIBudgetLedger.customer_id == customer_id, AIBudgetLedger.year_month == year_month
        )
    )
    spent_cents = (ledger.reserved_cents + ledger.actual_cents) if ledger is not None else 0
    return BudgetStatus(
        year_month=year_month,
        soft_cap_cents=soft_cap_cents,
        hard_cap_cents=hard_cap_cents,
        spent_cents=spent_cents,
        over_soft_budget=spent_cents > soft_cap_cents,
    )


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
    status: UsageEventStatus = UsageEventStatus.RECONCILED,
) -> AIUsageEvent:
    """NFR-COST-001's FinOps breakdown row — one per chat TURN (which may
    itself span several internal gateway calls across tool-call rounds;
    `usage`/`*_cost_cents` are already the SUM across all of them, so this
    never double-counts a turn's spend across multiple rows). `status`
    defaults to RECONCILED (a turn that completed normally); the caller
    passes REFUNDED for a turn that failed mid-way — see
    `doda.application.conversation_service.stream_message`'s exception
    handler, the only caller of the REFUNDED case."""
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
        status=status,
    )
    session.add(event)
    await session.flush()
    return event
