"""Task lifecycle — FR-TASK. Unlike Action, the TRD has no formal state
machine table for Task (compare section 4.2), so this uses the smallest
defensible set: forward progress or cancellation, no backtracking.
Reopening a DONE/CANCELLED task is a product decision the TRD does not
make, so it is deliberately left unsupported here rather than guessed at —
see CLAUDE.md known limitations. If real usage needs it, that's a change
request (QOIDA 2), not a bug fix.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doda.application.notification_service import create_notification
from doda.domain.base import utcnow
from doda.domain.notification.models import NotificationType
from doda.domain.task.models import Reminder, ReminderStatus, Task, TaskDecision, TaskHistory, TaskStatus

MAX_PAGE_SIZE = 200

ALLOWED_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.TODO: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED}),
    TaskStatus.IN_PROGRESS: frozenset({TaskStatus.DONE, TaskStatus.CANCELLED}),
    TaskStatus.DONE: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


class InvalidTaskTransition(Exception):
    def __init__(self, current: TaskStatus, target: TaskStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"{current.value} -> {target.value} is not an allowed task transition")


class ReminderConfirmationMismatchError(Exception):
    """confirm_reminder requires the caller to echo back the exact
    remind_at they are confirming (FR-TASK-005: the TIME itself is what
    gets confirmed, not just an opaque id) — raised when it does not
    match the stored value, e.g. a stale client showing an old request."""


class ReminderNotPendingError(Exception):
    """confirm_reminder/cancel_reminder called on a reminder that has
    already left the state they require (already CONFIRMED/CANCELLED/
    FIRED) — an ordinary state-machine guard, the same shape as
    InvalidTaskTransition above."""


class TaskParentNotFoundError(Exception):
    """Raised when parent_task_id doesn't resolve to a task in the SAME
    workspace. Postgres FK checks bypass RLS (referential integrity is
    evaluated across the whole table, not just RLS-visible rows), so
    relying on the FK alone would let a caller distinguish "this UUID is
    some task somewhere, even in another tenant" from "this UUID doesn't
    exist at all" via 200-vs-500 — a cross-tenant existence oracle
    (NFR-ISO-002). This check closes that off with an explicit,
    workspace-scoped lookup before the insert, same as
    workspace_service.add_workspace_member's cross-customer guard."""


async def create_task(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    workspace_id: uuid.UUID,
    owner_id: str,
    title: str,
    due_date: datetime | None = None,
    parent_task_id: uuid.UUID | None = None,
) -> Task:
    if parent_task_id is not None:
        parent = await session.get(Task, parent_task_id)
        if parent is None or parent.workspace_id != workspace_id:
            raise TaskParentNotFoundError(f"parent task {parent_task_id} not found in this workspace")

    task = Task(
        customer_id=customer_id,
        workspace_id=workspace_id,
        owner_id=owner_id,
        title=title,
        due_date=due_date,
        parent_task_id=parent_task_id,
        status=TaskStatus.TODO,
    )
    session.add(task)
    await session.flush()
    # FR-TASK-007: every status a task has ever held gets a history row,
    # including its birth into TODO — not just later transitions.
    session.add(
        TaskHistory(
            customer_id=customer_id,
            task_id=task.id,
            actor_id=owner_id,
            from_status=None,
            to_status=TaskStatus.TODO,
        )
    )
    await session.flush()
    return task


async def change_task_status(session: AsyncSession, task: Task, *, target: TaskStatus, actor_id: str) -> Task:
    # Re-lock and refresh `task` first (SELECT ... FOR UPDATE, same
    # technique as audit_service's chain-tip row) — the caller already
    # loaded `task` via a plain get() before this was called, so without
    # this, two near-simultaneous requests that both loaded it while it
    # was still e.g. TODO could both pass the transition check below and
    # both write a TaskHistory row for the same TODO -> IN_PROGRESS move.
    # populate_existing is required: a bare FOR UPDATE select does not by
    # itself refresh an already identity-mapped instance's attributes.
    await session.execute(
        select(Task).where(Task.id == task.id).with_for_update().execution_options(populate_existing=True)
    )
    if target not in ALLOWED_TASK_TRANSITIONS.get(task.status, frozenset()):
        raise InvalidTaskTransition(task.status, target)

    previous = task.status
    task.status = target
    await session.flush()
    session.add(
        TaskHistory(
            customer_id=task.customer_id,
            task_id=task.id,
            actor_id=actor_id,
            from_status=previous,
            to_status=target,
        )
    )
    await session.flush()

    if target is TaskStatus.DONE:
        # FR-NTF-002: notify the owner, not the actor — meaningful when a
        # workspace_admin closes someone else's task (authz_service allows
        # that override; the owner still deserves to know).
        await create_notification(
            session,
            customer_id=task.customer_id,
            workspace_id=task.workspace_id,
            recipient_id=task.owner_id,
            notification_type=NotificationType.COMPLETED_TASK,
            reference_type="task",
            reference_id=task.id,
            safe_metadata={"title": task.title},
        )
    return task


async def list_task_history(session: AsyncSession, task_id: uuid.UUID) -> list[TaskHistory]:
    result = await session.execute(
        select(TaskHistory).where(TaskHistory.task_id == task_id).order_by(TaskHistory.created_at)
    )
    return list(result.scalars())


async def record_task_decision(
    session: AsyncSession,
    task: Task,
    *,
    actor_id: str,
    variant: str,
    tradeoff: str,
    decision: str,
    reason: str,
) -> TaskDecision:
    """FR-TASK-003. Always an INSERT, never an UPDATE — recording a new
    decision about the same task does not touch any earlier row, it adds
    another one; 0020's trigger blocks UPDATE/DELETE outright so this is
    not merely a convention. `list_task_decisions`'s caller treats the
    newest row (by created_at) as the current decision."""
    record = TaskDecision(
        customer_id=task.customer_id,
        task_id=task.id,
        actor_id=actor_id,
        variant=variant,
        tradeoff=tradeoff,
        decision=decision,
        reason=reason,
    )
    session.add(record)
    await session.flush()
    return record


async def list_task_decisions(session: AsyncSession, task_id: uuid.UUID) -> list[TaskDecision]:
    result = await session.execute(
        select(TaskDecision).where(TaskDecision.task_id == task_id).order_by(TaskDecision.created_at)
    )
    return list(result.scalars())


async def request_reminder(
    session: AsyncSession, task: Task, *, actor_id: str, remind_at: datetime
) -> Reminder:
    """FR-TASK-005. Creates the REQUEST only — PENDING_CONFIRMATION,
    never fires, never notifies anyone, until confirm_reminder moves it
    to CONFIRMED. Deliberately no validation that remind_at is in the
    future: a reminder confirmed for a time already past will simply be
    picked up and fired on the very next run of fire_due_reminders,
    which is the correct, boring behavior for a "confirm this exact
    time" feature, not a special case to reject."""
    reminder = Reminder(
        customer_id=task.customer_id,
        workspace_id=task.workspace_id,
        task_id=task.id,
        actor_id=actor_id,
        remind_at=remind_at,
        status=ReminderStatus.PENDING_CONFIRMATION,
    )
    session.add(reminder)
    await session.flush()
    return reminder


async def confirm_reminder(
    session: AsyncSession, reminder: Reminder, *, remind_at: datetime, actor_id: str
) -> Reminder:
    if reminder.status is not ReminderStatus.PENDING_CONFIRMATION:
        raise ReminderNotPendingError(f"reminder {reminder.id} is {reminder.status.value}, not pending")
    if reminder.remind_at != remind_at:
        raise ReminderConfirmationMismatchError(
            f"reminder {reminder.id}'s current remind_at does not match what was confirmed"
        )
    reminder.status = ReminderStatus.CONFIRMED
    reminder.confirmed_at = utcnow()
    await session.flush()
    return reminder


async def cancel_reminder(session: AsyncSession, reminder: Reminder) -> Reminder:
    if reminder.status not in (ReminderStatus.PENDING_CONFIRMATION, ReminderStatus.CONFIRMED):
        raise ReminderNotPendingError(
            f"reminder {reminder.id} is {reminder.status.value}, cannot be cancelled"
        )
    reminder.status = ReminderStatus.CANCELLED
    await session.flush()
    return reminder


async def list_reminders_for_task(session: AsyncSession, task_id: uuid.UUID) -> list[Reminder]:
    result = await session.execute(
        select(Reminder).where(Reminder.task_id == task_id).order_by(Reminder.created_at)
    )
    return list(result.scalars())


async def fire_due_reminders(session: AsyncSession, *, now: datetime | None = None) -> list[Reminder]:
    """Scans this transaction's tenant (customer_id already bound by
    tenant_scoped_session) for CONFIRMED reminders whose remind_at has
    passed, fires a REMINDER_DUE notification to the requester for each,
    and marks them FIRED. Called by backend/scripts/fire_due_reminders_job.py
    once per customer, the same "standalone script iterates customers via
    UserCustomerIndex, calls one tenant-scoped application function per
    customer" shape as verify_audit_chain_job.py/
    find_stuck_running_actions.py."""
    now = now or utcnow()
    result = await session.execute(
        select(Reminder).where(Reminder.status == ReminderStatus.CONFIRMED, Reminder.remind_at <= now)
    )
    due = list(result.scalars())
    for reminder in due:
        task = await session.get(Task, reminder.task_id)
        assert task is not None  # FK guarantees this; RLS already scopes both to the same tenant
        await create_notification(
            session,
            customer_id=reminder.customer_id,
            workspace_id=reminder.workspace_id,
            recipient_id=reminder.actor_id,
            notification_type=NotificationType.REMINDER_DUE,
            reference_type="task",
            reference_id=task.id,
            safe_metadata={"title": task.title},
        )
        reminder.status = ReminderStatus.FIRED
        reminder.fired_at = now
    if due:
        await session.flush()
    return due


async def list_tasks_for_workspace(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    status: TaskStatus | None = None,
    limit: int = 50,
) -> list[Task]:
    """Every workspace member may see every task in their own workspace —
    the same visibility api/tasks.py's existing get-by-id already grants
    (it checks workspace membership only, never task ownership); this list
    endpoint was simply missing until now, the same class of gap
    GET /v1/me/workspaces closed one level up."""
    query = select(Task).where(Task.workspace_id == workspace_id)
    if status is not None:
        query = query.where(Task.status == status)
    query = query.order_by(Task.created_at.desc()).limit(min(limit, MAX_PAGE_SIZE))
    result = await session.execute(query)
    return list(result.scalars())


PLAN_WINDOWS = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}


async def generate_task_plan(
    session: AsyncSession, *, workspace_id: uuid.UUID, period: str, limit: int = 100
) -> list[Task]:
    """FR-TASK-002: "Kunlik/haftalik reja generatsiyasi... reja faqat
    joriy workspace tasklaridan tuziladi." No AI involved — a "plan" here
    is deterministic: every open (not DONE/CANCELLED) task in THIS
    workspace whose due_date falls within the period's window from now,
    earliest first. An already-overdue task (due_date in the past) is
    included in both windows — it still needs doing, arguably more
    urgently, not less. A task with no due_date at all is excluded: a
    time-boxed daily/weekly plan is specifically about what's due when,
    not the full backlog (list_tasks_for_workspace already covers that).

    `period` must be a key of PLAN_WINDOWS ("daily" or "weekly") — the
    caller (api/tasks.py) validates this via a Literal type before it
    ever reaches here, so an invalid value is a programming error, not a
    user input to handle gracefully."""
    window = PLAN_WINDOWS[period]
    horizon = utcnow() + window
    query = (
        select(Task)
        .where(
            Task.workspace_id == workspace_id,
            Task.due_date.is_not(None),
            Task.due_date <= horizon,
            Task.status.not_in((TaskStatus.DONE, TaskStatus.CANCELLED)),
        )
        .order_by(Task.due_date.asc())
        .limit(min(limit, MAX_PAGE_SIZE))
    )
    result = await session.execute(query)
    return list(result.scalars())
