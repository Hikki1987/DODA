"""AI usage/cost accounting domain — NFR-COST-001 ("Customer/workspace/
model bo'yicha" FinOps breakdown) and TRD's "so'rov identifikatori, model,
davomiylik, token sarfi va holatni qayd etish" requirement.

`UsageMode` intentionally duplicates `doda.ai.types.ChatMode`'s three
values rather than importing it: per 6.2, a Domain module never reaches
up into another layer (AI sits above Domain in the layer table, 6.1) —
the application layer converts between the two at the boundary
(`doda.application.ai_budget_service`), the same way `doda.domain.action`
keeps its own `RiskLevel`/`ActionStatus` rather than importing anything
from outside the domain layer.

Money is stored as integer cents (`*_cents` columns), never a float —
the usual reason: float arithmetic on money silently drifts, and this
ledger is read-modify-written many times over a customer's billing month
(`AIBudgetLedger`).
"""

import enum
import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from doda.domain.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class UsageMode(enum.StrEnum):
    FAST = "FAST"
    STANDARD = "STANDARD"
    DEEP = "DEEP"


class UsageProvider(enum.StrEnum):
    """Duplicates `doda.ai.types.Provider`'s three values for the same
    layering reason `UsageMode` duplicates `ChatMode` — see module
    docstring."""

    OPENAI = "OPENAI"
    GEMINI = "GEMINI"
    CLAUDE = "CLAUDE"


class UsageEventStatus(enum.StrEnum):
    """RESERVED: cost estimated and reserved against the monthly budget,
    before the provider call. RECONCILED: the provider call finished and
    actual usage/cost replaced the estimate. REFUNDED: the provider call
    failed before billing any real usage, and the reservation was given
    back — see `doda.application.ai_budget_service.release_reservation`.
    """

    RESERVED = "RESERVED"
    RECONCILED = "RECONCILED"
    REFUNDED = "REFUNDED"


class AIUsageEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One row per gateway call attempt — append-only in spirit (rows are
    updated in place from RESERVED -> RECONCILED/REFUNDED rather than a
    new row per state, unlike AuditEvent, because this is a cost ledger
    entry being finalized, not an immutable historical fact being
    recorded; the *audit* trail for the same call is a separate
    `ai.gateway_call.v1` AuditEvent, written only once reconciled)."""

    __tablename__ = "ai_usage_events"

    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    trace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    actor_id: Mapped[str] = mapped_column(String(256))
    provider: Mapped[UsageProvider] = mapped_column(
        SAEnum(UsageProvider, name="ai_usage_provider", native_enum=False, length=16)
    )
    mode: Mapped[UsageMode] = mapped_column(
        SAEnum(UsageMode, name="ai_usage_mode", native_enum=False, length=16)
    )
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cached_input_tokens: Mapped[int] = mapped_column(default=0)
    estimated_cost_cents: Mapped[int] = mapped_column(default=0)
    actual_cost_cents: Mapped[int | None] = mapped_column(default=None)
    status: Mapped[UsageEventStatus] = mapped_column(
        SAEnum(UsageEventStatus, name="ai_usage_event_status", native_enum=False, length=16),
        default=UsageEventStatus.RESERVED,
    )


class AIBudgetLedger(Base):
    """One row per (customer, calendar month) — same "row's existence/
    value is the whole state" shape as `WorkspaceKillSwitch`. Locked with
    `SELECT ... FOR UPDATE` before every read-modify-write
    (`doda.application.ai_budget_service`) — the same proven,
    concurrency-safe pattern already used for `audit_chain_tips`, task
    status transitions, approval consumption, kill-switch engage, and the
    last-owner invariant elsewhere in this codebase. Without that lock,
    two concurrent requests near the budget cap could both read a
    still-under-cap total and both be admitted — exactly the TOCTOU class
    this project has fixed five times already; the explicit instruction
    here ("bir vaqtning o'zida kelgan so'rovlar budjet cheklovini chetlab
    o'tmasin") means this must not become a sixth.
    """

    __tablename__ = "ai_budget_ledgers"

    customer_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    year_month: Mapped[str] = mapped_column(String(7), primary_key=True)
    """"YYYY-MM", UTC calendar month."""
    reserved_cents: Mapped[int] = mapped_column(default=0)
    """Sum of outstanding RESERVED AIUsageEvent estimates not yet reconciled."""
    actual_cents: Mapped[int] = mapped_column(default=0)
    """Sum of RECONCILED AIUsageEvent actual costs this month."""
