"""Shared helper for this directory's independent monitoring scripts.

Not a public application-layer module (see CLAUDE.md's 6-bo'lim
architecture layering — this is Operations, not something the app
itself calls) — just local reuse between find_stuck_running_actions.py
and find_stuck_compensating_actions.py, which were otherwise
near-identical: both walk a customer's Actions in one status, look up
the audit event that recorded entering that status, and flag any whose
event is older than a threshold.
"""

import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doda.domain.action.models import Action, ActionStatus
from doda.domain.audit.models import AuditEvent


async def find_actions_stuck_in_status(
    db: AsyncSession, *, status: ActionStatus, entered_status_event_type: str
) -> list[tuple[Action, datetime | None]]:
    """Every Action currently in `status` for this tenant-scoped session,
    paired with the timestamp its own `entered_status_event_type` audit
    event was recorded — None if that event is missing, which
    "shouldn't happen" per `apply_transition`'s own guarantee that every
    transition is audited; each caller decides how to report that case.

    One query per customer rather than per action — no precedent (or
    index) in this codebase for a JSONB ->> match, and the realistic
    event count per customer is small enough that filtering in Python
    is simpler and just as correct.
    """
    actions = (await db.scalars(select(Action).where(Action.status == status))).all()
    if not actions:
        return []
    events = (
        await db.scalars(select(AuditEvent).where(AuditEvent.event_type == entered_status_event_type))
    ).all()
    since_by_action_id = {event.safe_metadata.get("action_id"): event.occurred_at for event in events}
    return [(action, since_by_action_id.get(str(action.id))) for action in actions]


def report_stuck_actions(
    pairs: list[tuple[Action, datetime | None]],
    *,
    customer_id: uuid.UUID,
    cutoff: datetime,
    since_label: str,
    missing_reason: str,
    ok_label: str,
) -> bool:
    """Prints one line per Action in `pairs` (STUCK ones to stderr, OK
    ones to stdout) and returns whether any were STUCK — the shared body
    of find_stuck_running_actions.py's and find_stuck_compensating_
    actions.py's `main()` loops, which were otherwise near-identical
    beyond their status/event-type/threshold/labels."""
    any_stuck = False
    for action, since in pairs:
        if since is None:
            # Shouldn't happen — apply_transition always records this
            # event on the corresponding transition. Report it rather
            # than silently skip, since it means this script's own
            # assumption about how the Action reached this status is
            # wrong.
            any_stuck = True
            print(
                f"customer={customer_id} action={action.id} tool={action.tool_name} "
                f"STUCK reason={missing_reason}",
                file=sys.stderr,
            )
        elif since < cutoff:
            any_stuck = True
            age = datetime.now(UTC) - since
            print(
                f"customer={customer_id} action={action.id} tool={action.tool_name} "
                f"STUCK {since_label}={since.isoformat()} age={age}",
                file=sys.stderr,
            )
        else:
            print(f"customer={customer_id} action={action.id} tool={action.tool_name} {ok_label}")
    return any_stuck
