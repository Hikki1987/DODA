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
            customer_id=customer_id, task_id=task.id, actor_id=owner_id, from_status=None, to_status=TaskStatus.TODO
        )
    )
    await session.flush()
    return task


async def change_task_status(
    session: AsyncSession, task: Task, *, target: TaskStatus, actor_id: str
) -> Task:
    if target not in ALLOWED_TASK_TRANSITIONS.get(task.status, frozenset()):
        raise InvalidTaskTransition(task.status, target)

    previous = task.status
    task.status = target
    await session.flush()
    session.add(
        TaskHistory(
            customer_id=task.customer_id, task_id=task.id, actor_id=actor_id, from_status=previous, to_status=target
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
