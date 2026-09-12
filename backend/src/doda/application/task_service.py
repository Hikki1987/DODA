"""Task lifecycle — FR-TASK. Unlike Action, the TRD has no formal state
machine table for Task (compare section 4.2), so this uses the smallest
defensible set: forward progress or cancellation, no backtracking.
Reopening a DONE/CANCELLED task is a product decision the TRD does not
make, so it is deliberately left unsupported here rather than guessed at —
see CLAUDE.md known limitations. If real usage needs it, that's a change
request (QOIDA 2), not a bug fix.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doda.application.notification_service import create_notification
from doda.domain.notification.models import NotificationType
from doda.domain.task.models import Task, TaskHistory, TaskStatus

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
