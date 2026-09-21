"""Task endpoints — FR-TASK. Same authoritative-chain pattern as
api/actions.py: every handler gets its tenant/authz context only from
RequestContext, never from client-supplied customer_id/actor_id."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from doda.api.dependencies import RequestContext, get_request_context
from doda.api.task_schemas import (
    AttachDocumentRequest,
    ChangeTaskStatusRequest,
    ConfirmReminderRequest,
    CreateTaskRequest,
    RecordTaskDecisionRequest,
    ReminderOut,
    RequestReminderRequest,
    TaskAttachmentOut,
    TaskDecisionOut,
    TaskHistoryEntryOut,
    TaskOut,
)
from doda.application.authz_service import authorize_create_task, authorize_task_mutation
from doda.application.task_service import (
    ResolvedTaskAttachment,
    attach_document_to_task,
    cancel_reminder,
    change_task_status,
    confirm_reminder,
    create_task,
    detach_task_attachment,
    generate_task_plan,
    list_reminders_for_task,
    list_task_attachments,
    list_task_decisions,
    list_task_history,
    list_tasks_for_workspace,
    record_task_decision,
    request_reminder,
)
from doda.domain.task.models import Reminder, Task, TaskAttachment, TaskDecision, TaskStatus

router = APIRouter(tags=["tasks"])


def _to_task_out(task: Task) -> TaskOut:
    return TaskOut(
        id=task.id,
        workspace_id=task.workspace_id,
        owner_id=task.owner_id,
        title=task.title,
        status=task.status,
        due_date=task.due_date,
        parent_task_id=task.parent_task_id,
    )


@router.post("/v1/workspaces/{workspace_id}/tasks", response_model=TaskOut)
async def create_workspace_task(
    body: CreateTaskRequest, ctx: RequestContext = Depends(get_request_context)
) -> TaskOut:
    authorize_create_task(ctx.workspace)
    task = await create_task(
        ctx.db,
        customer_id=ctx.workspace.customer_id,
        workspace_id=ctx.workspace.workspace_id,
        owner_id=f"user:{ctx.workspace.user_id}",
        title=body.title,
        due_date=body.due_date,
        parent_task_id=body.parent_task_id,
    )
    return _to_task_out(task)


@router.get("/v1/workspaces/{workspace_id}/tasks", response_model=list[TaskOut])
async def list_workspace_tasks(
    status: TaskStatus | None = None,
    limit: int = Query(default=50, le=200),
    ctx: RequestContext = Depends(get_request_context),
) -> list[TaskOut]:
    tasks = await list_tasks_for_workspace(
        ctx.db, workspace_id=ctx.workspace.workspace_id, status=status, limit=limit
    )
    return [_to_task_out(task) for task in tasks]


@router.get("/v1/workspaces/{workspace_id}/tasks/plan", response_model=list[TaskOut])
async def get_workspace_task_plan(
    period: Literal["daily", "weekly"] = Query(default="daily"),
    ctx: RequestContext = Depends(get_request_context),
) -> list[TaskOut]:
    """FR-TASK-002. Registered ABOVE GET .../tasks/{task_id} below on
    purpose — Starlette matches routes in registration order, and that
    route's plain {task_id} path parameter would otherwise swallow
    "plan" as a (nonexistent) task id, so this route would never be
    reached if it came after (verified: temporarily moving this route
    below get_task reproduces exactly that — a 422 from the wrong
    handler, http.route={workspace_id}/tasks/{task_id} in the trace)."""
    tasks = await generate_task_plan(ctx.db, workspace_id=ctx.workspace.workspace_id, period=period)
    return [_to_task_out(task) for task in tasks]


async def _get_owned_task(ctx: RequestContext, task_id: uuid.UUID) -> Task:
    task = await ctx.db.get(Task, task_id)
    if task is None or task.workspace_id != ctx.workspace.workspace_id:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.get("/v1/workspaces/{workspace_id}/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: uuid.UUID, ctx: RequestContext = Depends(get_request_context)) -> TaskOut:
    task = await _get_owned_task(ctx, task_id)
    return _to_task_out(task)


@router.post("/v1/workspaces/{workspace_id}/tasks/{task_id}/status", response_model=TaskOut)
async def change_workspace_task_status(
    task_id: uuid.UUID,
    body: ChangeTaskStatusRequest,
    ctx: RequestContext = Depends(get_request_context),
) -> TaskOut:
    task = await _get_owned_task(ctx, task_id)
    authorize_task_mutation(ctx.workspace, task)
    task = await change_task_status(
        ctx.db, task, target=body.target_status, actor_id=f"user:{ctx.workspace.user_id}"
    )
    return _to_task_out(task)


@router.get(
    "/v1/workspaces/{workspace_id}/tasks/{task_id}/history",
    response_model=list[TaskHistoryEntryOut],
)
async def get_task_history(
    task_id: uuid.UUID, ctx: RequestContext = Depends(get_request_context)
) -> list[TaskHistoryEntryOut]:
    await _get_owned_task(ctx, task_id)  # 404s before revealing any history exists
    history = await list_task_history(ctx.db, task_id)
    return [
        TaskHistoryEntryOut(
            id=entry.id,
            actor_id=entry.actor_id,
            from_status=entry.from_status,
            to_status=entry.to_status,
            created_at=entry.created_at,
        )
        for entry in history
    ]


def _to_task_decision_out(record: TaskDecision) -> TaskDecisionOut:
    return TaskDecisionOut(
        id=record.id,
        actor_id=record.actor_id,
        variant=record.variant,
        tradeoff=record.tradeoff,
        decision=record.decision,
        reason=record.reason,
        created_at=record.created_at,
    )


@router.post(
    "/v1/workspaces/{workspace_id}/tasks/{task_id}/decisions",
    response_model=TaskDecisionOut,
)
async def record_workspace_task_decision(
    task_id: uuid.UUID,
    body: RecordTaskDecisionRequest,
    ctx: RequestContext = Depends(get_request_context),
) -> TaskDecisionOut:
    """FR-TASK-003. Same authorization as changing the task's status
    (owner or workspace_admin) — recording a decision is task-mutating
    the same way a status change is, not a passive read."""
    task = await _get_owned_task(ctx, task_id)
    authorize_task_mutation(ctx.workspace, task)
    record = await record_task_decision(
        ctx.db,
        task,
        actor_id=f"user:{ctx.workspace.user_id}",
        variant=body.variant,
        tradeoff=body.tradeoff,
        decision=body.decision,
        reason=body.reason,
    )
    return _to_task_decision_out(record)


@router.get(
    "/v1/workspaces/{workspace_id}/tasks/{task_id}/decisions",
    response_model=list[TaskDecisionOut],
)
async def get_task_decisions(
    task_id: uuid.UUID, ctx: RequestContext = Depends(get_request_context)
) -> list[TaskDecisionOut]:
    await _get_owned_task(ctx, task_id)  # 404s before revealing any decision exists
    decisions = await list_task_decisions(ctx.db, task_id)
    return [_to_task_decision_out(record) for record in decisions]


def _to_task_attachment_out(record: ResolvedTaskAttachment) -> TaskAttachmentOut:
    return TaskAttachmentOut(
        id=record.id,
        document_id=record.document_id,
        attached_by=record.attached_by,
        created_at=record.created_at,
        broken=record.broken,
        filename=record.filename,
        content_type=record.content_type,
        size_bytes=record.size_bytes,
    )


@router.post(
    "/v1/workspaces/{workspace_id}/tasks/{task_id}/attachments",
    response_model=TaskAttachmentOut,
)
async def attach_task_document(
    task_id: uuid.UUID,
    body: AttachDocumentRequest,
    ctx: RequestContext = Depends(get_request_context),
) -> TaskAttachmentOut:
    """FR-TASK-006. Same authorization as recording a decision (owner or
    workspace_admin) — attaching evidence is task-mutating the same way."""
    task = await _get_owned_task(ctx, task_id)
    authorize_task_mutation(ctx.workspace, task)
    resolved = await attach_document_to_task(
        ctx.db, task, document_id=body.document_id, actor_id=f"user:{ctx.workspace.user_id}"
    )
    return _to_task_attachment_out(resolved)


@router.get(
    "/v1/workspaces/{workspace_id}/tasks/{task_id}/attachments",
    response_model=list[TaskAttachmentOut],
)
async def get_task_attachments(
    task_id: uuid.UUID, ctx: RequestContext = Depends(get_request_context)
) -> list[TaskAttachmentOut]:
    await _get_owned_task(ctx, task_id)  # 404s before revealing any attachment exists
    attachments = await list_task_attachments(ctx.db, task_id)
    return [_to_task_attachment_out(record) for record in attachments]


async def _get_owned_attachment(
    ctx: RequestContext, task_id: uuid.UUID, attachment_id: uuid.UUID
) -> TaskAttachment:
    attachment = await ctx.db.get(TaskAttachment, attachment_id)
    if (
        attachment is None
        or attachment.task_id != task_id
        or attachment.workspace_id != ctx.workspace.workspace_id
    ):
        raise HTTPException(status_code=404, detail="attachment not found")
    return attachment


@router.delete(
    "/v1/workspaces/{workspace_id}/tasks/{task_id}/attachments/{attachment_id}",
    status_code=204,
)
async def detach_task_document(
    task_id: uuid.UUID,
    attachment_id: uuid.UUID,
    ctx: RequestContext = Depends(get_request_context),
) -> None:
    task = await _get_owned_task(ctx, task_id)
    authorize_task_mutation(ctx.workspace, task)
    attachment = await _get_owned_attachment(ctx, task_id, attachment_id)
    await detach_task_attachment(ctx.db, attachment)


def _to_reminder_out(reminder: Reminder) -> ReminderOut:
    return ReminderOut(
        id=reminder.id,
        task_id=reminder.task_id,
        actor_id=reminder.actor_id,
        remind_at=reminder.remind_at,
        status=reminder.status,
        confirmed_at=reminder.confirmed_at,
        fired_at=reminder.fired_at,
        created_at=reminder.created_at,
    )


async def _get_owned_reminder(ctx: RequestContext, task_id: uuid.UUID, reminder_id: uuid.UUID) -> Reminder:
    reminder = await ctx.db.get(Reminder, reminder_id)
    if reminder is None or reminder.task_id != task_id or reminder.workspace_id != ctx.workspace.workspace_id:
        raise HTTPException(status_code=404, detail="reminder not found")
    return reminder


@router.post(
    "/v1/workspaces/{workspace_id}/tasks/{task_id}/reminders",
    response_model=ReminderOut,
)
async def request_task_reminder(
    task_id: uuid.UUID,
    body: RequestReminderRequest,
    ctx: RequestContext = Depends(get_request_context),
) -> ReminderOut:
    """FR-TASK-005. Same authorization as recording a decision (owner or
    workspace_admin) — this only creates a PENDING_CONFIRMATION request,
    never anything that actually fires on its own."""
    task = await _get_owned_task(ctx, task_id)
    authorize_task_mutation(ctx.workspace, task)
    reminder = await request_reminder(
        ctx.db, task, actor_id=f"user:{ctx.workspace.user_id}", remind_at=body.remind_at
    )
    return _to_reminder_out(reminder)


@router.get(
    "/v1/workspaces/{workspace_id}/tasks/{task_id}/reminders",
    response_model=list[ReminderOut],
)
async def get_task_reminders(
    task_id: uuid.UUID, ctx: RequestContext = Depends(get_request_context)
) -> list[ReminderOut]:
    await _get_owned_task(ctx, task_id)  # 404s before revealing any reminder exists
    reminders = await list_reminders_for_task(ctx.db, task_id)
    return [_to_reminder_out(reminder) for reminder in reminders]


@router.post(
    "/v1/workspaces/{workspace_id}/tasks/{task_id}/reminders/{reminder_id}/confirm",
    response_model=ReminderOut,
)
async def confirm_task_reminder(
    task_id: uuid.UUID,
    reminder_id: uuid.UUID,
    body: ConfirmReminderRequest,
    ctx: RequestContext = Depends(get_request_context),
) -> ReminderOut:
    task = await _get_owned_task(ctx, task_id)
    authorize_task_mutation(ctx.workspace, task)
    reminder = await _get_owned_reminder(ctx, task_id, reminder_id)
    reminder = await confirm_reminder(ctx.db, reminder, remind_at=body.remind_at)
    return _to_reminder_out(reminder)


@router.post(
    "/v1/workspaces/{workspace_id}/tasks/{task_id}/reminders/{reminder_id}/cancel",
    response_model=ReminderOut,
)
async def cancel_task_reminder(
    task_id: uuid.UUID,
    reminder_id: uuid.UUID,
    ctx: RequestContext = Depends(get_request_context),
) -> ReminderOut:
    task = await _get_owned_task(ctx, task_id)
    authorize_task_mutation(ctx.workspace, task)
    reminder = await _get_owned_reminder(ctx, task_id, reminder_id)
    reminder = await cancel_reminder(ctx.db, reminder)
    return _to_reminder_out(reminder)
